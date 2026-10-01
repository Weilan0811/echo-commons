from __future__ import annotations

from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from enum import StrEnum
from uuid import UUID

from echo_commons.domain.errors import (
    DomainInvariantError,
    optional_utc,
    require_non_empty,
    require_sequence,
    require_utc,
)

QUIET_WINDOW_SECONDS = 6


class InputBatchStatus(StrEnum):
    COLLECTING = "collecting"
    WAITING = "waiting"
    ASSIGNED = "assigned"
    COVERED = "covered"
    TERMINAL_FAILED = "terminal_failed"


@dataclass(frozen=True, slots=True)
class InputBatch:
    """A contiguous set of player messages closed by a quiet window."""

    input_batch_id: UUID
    account_id: str
    conversation_id: str
    quiet_until_utc: datetime
    created_at_utc: datetime
    updated_at_utc: datetime
    status: InputBatchStatus | str = InputBatchStatus.COLLECTING
    sealed_at_utc: datetime | None = None
    task_id: UUID | None = None
    first_message_sequence: int | None = None
    last_message_sequence: int | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.input_batch_id, UUID):
            raise DomainInvariantError("input_batch_id must be a UUID")
        object.__setattr__(self, "account_id", require_non_empty(self.account_id, "account_id"))
        object.__setattr__(
            self, "conversation_id", require_non_empty(self.conversation_id, "conversation_id")
        )
        object.__setattr__(self, "status", InputBatchStatus(self.status))
        quiet_until = require_utc(self.quiet_until_utc, "quiet_until_utc")
        created = require_utc(self.created_at_utc, "created_at_utc")
        updated = require_utc(self.updated_at_utc, "updated_at_utc")
        sealed = optional_utc(self.sealed_at_utc, "sealed_at_utc")
        if updated < created:
            raise DomainInvariantError("updated_at_utc must not be earlier than created_at_utc")
        if quiet_until < created:
            raise DomainInvariantError("quiet_until_utc must not be earlier than created_at_utc")
        if sealed is not None and sealed < created:
            raise DomainInvariantError("sealed_at_utc must not be earlier than created_at_utc")
        if self.task_id is not None and not isinstance(self.task_id, UUID):
            raise DomainInvariantError("task_id must be a UUID or None")
        if self.first_message_sequence is None or self.last_message_sequence is None:
            if self.first_message_sequence is not None or self.last_message_sequence is not None:
                raise DomainInvariantError("first and last message sequence must be set together")
        else:
            first = require_sequence(self.first_message_sequence, "first_message_sequence")
            last = require_sequence(self.last_message_sequence, "last_message_sequence")
            if last < first:
                raise DomainInvariantError(
                    "last_message_sequence must not precede first_message_sequence"
                )
            object.__setattr__(self, "first_message_sequence", first)
            object.__setattr__(self, "last_message_sequence", last)
        if self.status is InputBatchStatus.COLLECTING:
            if sealed is not None or self.task_id is not None:
                raise DomainInvariantError("collecting batch cannot be sealed or assigned")
        elif self.first_message_sequence is None:
            raise DomainInvariantError("a non-collecting batch must contain messages")
        elif sealed is None:
            raise DomainInvariantError("a non-collecting batch must have sealed_at_utc")
        elif self.status is InputBatchStatus.WAITING and self.task_id is not None:
            raise DomainInvariantError("waiting batch cannot be assigned")
        elif (
            self.status
            in {
                InputBatchStatus.ASSIGNED,
                InputBatchStatus.COVERED,
                InputBatchStatus.TERMINAL_FAILED,
            }
            and self.task_id is None
        ):
            raise DomainInvariantError("assigned or terminal batch must reference a task")
        object.__setattr__(self, "quiet_until_utc", quiet_until)
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "updated_at_utc", updated)
        object.__setattr__(self, "sealed_at_utc", sealed)

    @classmethod
    def start(
        cls,
        *,
        input_batch_id: UUID,
        account_id: str,
        conversation_id: str,
        now_utc: datetime,
        first_message_sequence: int | None = None,
        quiet_window_seconds: int = QUIET_WINDOW_SECONDS,
    ) -> InputBatch:
        if quiet_window_seconds <= 0:
            raise DomainInvariantError("quiet_window_seconds must be positive")
        now = require_utc(now_utc, "now_utc")
        return cls(
            input_batch_id=input_batch_id,
            account_id=account_id,
            conversation_id=conversation_id,
            quiet_until_utc=now + timedelta(seconds=quiet_window_seconds),
            created_at_utc=now,
            updated_at_utc=now,
            first_message_sequence=first_message_sequence,
            last_message_sequence=first_message_sequence,
        )

    @property
    def has_messages(self) -> bool:
        return self.first_message_sequence is not None

    @property
    def is_terminal(self) -> bool:
        return self.status in {
            InputBatchStatus.COVERED,
            InputBatchStatus.TERMINAL_FAILED,
        }

    def is_quiet_elapsed(self, *, now_utc: datetime) -> bool:
        return require_utc(now_utc, "now_utc") >= self.quiet_until_utc

    def append_message(
        self,
        *,
        message_sequence: int,
        now_utc: datetime,
        quiet_window_seconds: int = QUIET_WINDOW_SECONDS,
    ) -> InputBatch:
        if self.status is not InputBatchStatus.COLLECTING:
            raise DomainInvariantError("only a collecting batch can receive a message")
        if quiet_window_seconds <= 0:
            raise DomainInvariantError("quiet_window_seconds must be positive")
        sequence = require_sequence(message_sequence, "message_sequence")
        now = require_utc(now_utc, "now_utc")
        if now < self.updated_at_utc:
            raise DomainInvariantError("batch time cannot move backwards")
        if self.last_message_sequence is not None and sequence <= self.last_message_sequence:
            raise DomainInvariantError("message_sequence must increase within a batch")
        first = self.first_message_sequence or sequence
        return replace(
            self,
            first_message_sequence=first,
            last_message_sequence=sequence,
            quiet_until_utc=now + timedelta(seconds=quiet_window_seconds),
            updated_at_utc=now,
        )

    def seal(self, *, now_utc: datetime) -> InputBatch:
        if self.status is not InputBatchStatus.COLLECTING:
            raise DomainInvariantError("only a collecting batch can be sealed")
        now = require_utc(now_utc, "now_utc")
        if not self.has_messages:
            raise DomainInvariantError("an empty batch cannot be sealed")
        if now < self.quiet_until_utc:
            raise DomainInvariantError("quiet window has not elapsed")
        return replace(
            self,
            status=InputBatchStatus.WAITING,
            sealed_at_utc=now,
            updated_at_utc=now,
        )

    def assign(self, *, task_id: UUID, now_utc: datetime) -> InputBatch:
        if self.status is not InputBatchStatus.WAITING:
            raise DomainInvariantError("only a waiting batch can be assigned")
        if not isinstance(task_id, UUID):
            raise DomainInvariantError("task_id must be a UUID")
        now = require_utc(now_utc, "now_utc")
        if now < self.updated_at_utc:
            raise DomainInvariantError("batch time cannot move backwards")
        return replace(self, status=InputBatchStatus.ASSIGNED, task_id=task_id, updated_at_utc=now)

    def cover(self, *, now_utc: datetime) -> InputBatch:
        if self.status is not InputBatchStatus.ASSIGNED:
            raise DomainInvariantError("only an assigned batch can be covered")
        now = require_utc(now_utc, "now_utc")
        if now < self.updated_at_utc:
            raise DomainInvariantError("batch time cannot move backwards")
        return replace(self, status=InputBatchStatus.COVERED, updated_at_utc=now)

    def fail_terminally(self, *, now_utc: datetime) -> InputBatch:
        if self.status is not InputBatchStatus.ASSIGNED:
            raise DomainInvariantError("only an assigned batch can fail terminally")
        now = require_utc(now_utc, "now_utc")
        if now < self.updated_at_utc:
            raise DomainInvariantError("batch time cannot move backwards")
        return replace(self, status=InputBatchStatus.TERMINAL_FAILED, updated_at_utc=now)
