"""Conversation task lifecycle, leases, retries, and frozen boundaries."""

from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from echo_server.domain.errors import (
    DomainInvariantError,
    optional_utc,
    require_non_empty,
    require_sequence,
    require_utc,
)


class TaskStatus(StrEnum):
    PENDING = "pending"
    PROCESSING = "processing"
    RETRY_WAIT = "retry_wait"
    DEFERRED = "deferred"
    COMPLETED = "completed"
    FAILED = "failed"


@dataclass(frozen=True, slots=True)
class ConversationTask:
    """One logical reply task; provider retries reuse its task_id."""

    task_id: UUID
    account_id: str
    conversation_id: str
    character_id: str
    input_max_message_sequence: int
    context_max_message_sequence: int
    world_state_version: int
    character_state_version: int
    context_version: str
    available_at_utc: datetime
    created_at_utc: datetime
    updated_at_utc: datetime
    trace_id: UUID
    status: TaskStatus | str = TaskStatus.PENDING
    attempt_count: int = 0
    lease_generation: int = 0
    lease_owner: str | None = None
    lease_until_utc: datetime | None = None
    last_error_code: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.task_id, UUID) or not isinstance(self.trace_id, UUID):
            raise DomainInvariantError("task_id and trace_id must be UUIDs")
        object.__setattr__(self, "account_id", require_non_empty(self.account_id, "account_id"))
        object.__setattr__(
            self, "conversation_id", require_non_empty(self.conversation_id, "conversation_id")
        )
        object.__setattr__(
            self, "character_id", require_non_empty(self.character_id, "character_id")
        )
        object.__setattr__(
            self,
            "input_max_message_sequence",
            require_sequence(self.input_max_message_sequence, "input_max_message_sequence"),
        )
        object.__setattr__(
            self,
            "context_max_message_sequence",
            require_sequence(self.context_max_message_sequence, "context_max_message_sequence"),
        )
        if self.context_max_message_sequence < self.input_max_message_sequence:
            raise DomainInvariantError("context boundary must include the task input boundary")
        object.__setattr__(
            self,
            "world_state_version",
            require_sequence(self.world_state_version, "world_state_version", minimum=0),
        )
        object.__setattr__(
            self,
            "character_state_version",
            require_sequence(self.character_state_version, "character_state_version", minimum=0),
        )
        object.__setattr__(
            self, "context_version", require_non_empty(self.context_version, "context_version")
        )
        object.__setattr__(self, "status", TaskStatus(self.status))
        if (
            not isinstance(self.attempt_count, int)
            or isinstance(self.attempt_count, bool)
            or self.attempt_count < 0
        ):
            raise DomainInvariantError("attempt_count must be an integer >= 0")
        object.__setattr__(
            self,
            "lease_generation",
            require_sequence(self.lease_generation, "lease_generation", minimum=0),
        )
        if self.last_error_code is not None:
            object.__setattr__(
                self, "last_error_code", require_non_empty(self.last_error_code, "last_error_code")
            )
        available = require_utc(self.available_at_utc, "available_at_utc")
        created = require_utc(self.created_at_utc, "created_at_utc")
        updated = require_utc(self.updated_at_utc, "updated_at_utc")
        lease_until = optional_utc(self.lease_until_utc, "lease_until_utc")
        if updated < created:
            raise DomainInvariantError("updated_at_utc must not be earlier than created_at_utc")
        if available < created:
            raise DomainInvariantError("available_at_utc must not be earlier than created_at_utc")
        if self.status is TaskStatus.PROCESSING:
            if not self.lease_owner or lease_until is None or lease_until <= updated:
                raise DomainInvariantError("processing task must have a future lease")
        elif self.lease_owner is not None or lease_until is not None:
            raise DomainInvariantError("only a processing task may have a lease")
        object.__setattr__(self, "available_at_utc", available)
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "updated_at_utc", updated)
        object.__setattr__(self, "lease_until_utc", lease_until)

    @classmethod
    def create(
        cls,
        *,
        task_id: UUID,
        account_id: str,
        conversation_id: str,
        character_id: str,
        input_max_message_sequence: int,
        context_max_message_sequence: int,
        world_state_version: int,
        character_state_version: int,
        context_version: str,
        trace_id: UUID,
        now_utc: datetime,
    ) -> ConversationTask:
        now = require_utc(now_utc, "now_utc")
        return cls(
            task_id=task_id,
            account_id=account_id,
            conversation_id=conversation_id,
            character_id=character_id,
            input_max_message_sequence=input_max_message_sequence,
            context_max_message_sequence=context_max_message_sequence,
            world_state_version=world_state_version,
            character_state_version=character_state_version,
            context_version=context_version,
            available_at_utc=now,
            created_at_utc=now,
            updated_at_utc=now,
            trace_id=trace_id,
        )

    @property
    def is_terminal(self) -> bool:
        return self.status in {TaskStatus.COMPLETED, TaskStatus.FAILED}

    def has_valid_lease(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
    ) -> bool:
        if self.status is not TaskStatus.PROCESSING or self.lease_owner != worker_id:
            return False
        if attempt_count is not None and self.attempt_count != attempt_count:
            return False
        if lease_generation is not None and self.lease_generation != lease_generation:
            return False
        now = require_utc(now_utc, "now_utc")
        return self.lease_until_utc is not None and self.lease_until_utc > now

    def claim(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        lease_until_utc: datetime,
    ) -> ConversationTask:
        owner = require_non_empty(worker_id, "worker_id")
        now = require_utc(now_utc, "now_utc")
        lease_until = require_utc(lease_until_utc, "lease_until_utc")
        if self.status not in {TaskStatus.PENDING, TaskStatus.RETRY_WAIT}:
            raise DomainInvariantError("only pending or retry-wait tasks can be claimed")
        if now < self.available_at_utc:
            raise DomainInvariantError("task is not available yet")
        if lease_until <= now:
            raise DomainInvariantError("lease must expire in the future")
        return replace(
            self,
            status=TaskStatus.PROCESSING,
            attempt_count=self.attempt_count + 1,
            lease_generation=self.lease_generation + 1,
            lease_owner=owner,
            lease_until_utc=lease_until,
            updated_at_utc=now,
        )

    def complete(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
    ) -> ConversationTask:
        now = require_utc(now_utc, "now_utc")
        self._require_active_lease(
            worker_id=worker_id,
            now=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        return replace(
            self,
            status=TaskStatus.COMPLETED,
            lease_owner=None,
            lease_until_utc=None,
            last_error_code=None,
            updated_at_utc=now,
        )

    def retry_or_fail(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        available_at_utc: datetime,
        error_code: str,
        max_attempts: int,
        lease_generation: int | None = None,
        attempt_count: int | None = None,
    ) -> ConversationTask:
        now = require_utc(now_utc, "now_utc")
        available = require_utc(available_at_utc, "available_at_utc")
        code = require_non_empty(error_code, "error_code")
        max_attempts = require_sequence(max_attempts, "max_attempts")
        self._require_active_lease(
            worker_id=worker_id,
            now=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        if available < now:
            raise DomainInvariantError("retry availability cannot be earlier than now")
        status = TaskStatus.FAILED if self.attempt_count >= max_attempts else TaskStatus.RETRY_WAIT
        return replace(
            self,
            status=status,
            available_at_utc=available,
            lease_owner=None,
            lease_until_utc=None,
            last_error_code=code,
            updated_at_utc=now,
        )

    def fail(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        error_code: str,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
    ) -> ConversationTask:
        now = require_utc(now_utc, "now_utc")
        code = require_non_empty(error_code, "error_code")
        self._require_active_lease(
            worker_id=worker_id,
            now=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        return replace(
            self,
            status=TaskStatus.FAILED,
            lease_owner=None,
            lease_until_utc=None,
            last_error_code=code,
            updated_at_utc=now,
        )

    def defer(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        reason_code: str,
        available_at_utc: datetime | None = None,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
    ) -> ConversationTask:
        now = require_utc(now_utc, "now_utc")
        code = require_non_empty(reason_code, "reason_code")
        self._require_active_lease(
            worker_id=worker_id,
            now=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        available = (
            now if available_at_utc is None else require_utc(available_at_utc, "available_at_utc")
        )
        if available < now:
            raise DomainInvariantError("deferred availability cannot be earlier than now")
        return replace(
            self,
            status=TaskStatus.DEFERRED,
            available_at_utc=available,
            lease_owner=None,
            lease_until_utc=None,
            last_error_code=code,
            updated_at_utc=now,
        )

    def resume(self, *, now_utc: datetime) -> ConversationTask:
        now = require_utc(now_utc, "now_utc")
        if self.status is not TaskStatus.DEFERRED:
            raise DomainInvariantError("only a deferred task can resume")
        if now < self.updated_at_utc:
            raise DomainInvariantError("task time cannot move backwards")
        return replace(
            self,
            status=TaskStatus.PENDING,
            available_at_utc=now,
            last_error_code=None,
            updated_at_utc=now,
        )

    def recover_expired(self, *, now_utc: datetime) -> ConversationTask:
        now = require_utc(now_utc, "now_utc")
        if self.status is not TaskStatus.PROCESSING:
            raise DomainInvariantError("only a processing task can recover an expired lease")
        if self.lease_until_utc is None or self.lease_until_utc > now:
            raise DomainInvariantError("task lease has not expired")
        return replace(
            self,
            status=TaskStatus.RETRY_WAIT,
            available_at_utc=now,
            lease_owner=None,
            lease_until_utc=None,
            last_error_code=self.last_error_code or "lease_expired",
            updated_at_utc=now,
        )

    def renew_lease(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        lease_until_utc: datetime,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
    ) -> ConversationTask:
        now = require_utc(now_utc, "now_utc")
        lease_until = require_utc(lease_until_utc, "lease_until_utc")
        self._require_active_lease(
            worker_id=worker_id,
            now=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        )
        if lease_until <= now:
            raise DomainInvariantError("lease must expire in the future")
        return replace(self, lease_until_utc=lease_until, updated_at_utc=now)

    def _require_active_lease(
        self,
        *,
        worker_id: str,
        now: datetime,
        attempt_count: int | None = None,
        lease_generation: int | None = None,
    ) -> None:
        owner = require_non_empty(worker_id, "worker_id")
        if now < self.updated_at_utc:
            raise DomainInvariantError("task time cannot move backwards")
        if not self.has_valid_lease(
            worker_id=owner,
            now_utc=now,
            attempt_count=attempt_count,
            lease_generation=lease_generation,
        ):
            raise DomainInvariantError("task lease is missing, mismatched, or expired")
