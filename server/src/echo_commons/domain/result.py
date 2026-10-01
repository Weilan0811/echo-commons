from __future__ import annotations

import json
from collections.abc import Sequence
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from echo_commons.domain.errors import (
    DomainInvariantError,
    optional_utc,
    require_non_empty,
    require_sequence,
    require_utc,
)


class AgentResultStatus(StrEnum):
    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"


@dataclass(frozen=True, slots=True)
class AgentResult:
    """An untrusted Agent candidate; approval does not itself write a message."""

    result_id: UUID
    task_id: UUID
    attempt_no: int
    agent_id: str
    agent_kind: str
    invocation_id: UUID
    result_kind: str
    schema_version: str
    context_version: str
    payload_json: str
    created_at_utc: datetime
    status: AgentResultStatus | str = AgentResultStatus.PENDING
    decision_code: str | None = None
    decided_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.result_id, UUID) or not isinstance(self.task_id, UUID):
            raise DomainInvariantError("result_id and task_id must be UUIDs")
        if not isinstance(self.invocation_id, UUID):
            raise DomainInvariantError("invocation_id must be a UUID")
        object.__setattr__(self, "attempt_no", require_sequence(self.attempt_no, "attempt_no"))
        for field_name in (
            "agent_id",
            "agent_kind",
            "result_kind",
            "schema_version",
            "context_version",
        ):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        if not isinstance(self.payload_json, str) or not self.payload_json.strip():
            raise DomainInvariantError("payload_json must be a non-empty JSON string")
        try:
            json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise DomainInvariantError("payload_json must contain valid JSON") from exc
        object.__setattr__(self, "status", AgentResultStatus(self.status))
        created = require_utc(self.created_at_utc, "created_at_utc")
        decided = optional_utc(self.decided_at_utc, "decided_at_utc")
        if self.status is AgentResultStatus.PENDING:
            if self.decision_code is not None or decided is not None:
                raise DomainInvariantError("a pending result cannot have a decision")
        elif decided is None or self.decision_code is None:
            raise DomainInvariantError("a decided result must have a decision code and time")
        if self.decision_code is not None:
            object.__setattr__(
                self, "decision_code", require_non_empty(self.decision_code, "decision_code")
            )
        if decided is not None and decided < created:
            raise DomainInvariantError("decided_at_utc must not be earlier than created_at_utc")
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "decided_at_utc", decided)

    @property
    def is_terminal(self) -> bool:
        return self.status is not AgentResultStatus.PENDING

    def approve(
        self,
        *,
        decided_at_utc: datetime,
        decision_code: str = "approved",
    ) -> AgentResult:
        return self._decide(
            status=AgentResultStatus.APPROVED,
            decided_at_utc=decided_at_utc,
            decision_code=decision_code,
        )

    def reject(
        self,
        *,
        decided_at_utc: datetime,
        decision_code: str = "rejected",
    ) -> AgentResult:
        return self._decide(
            status=AgentResultStatus.REJECTED,
            decided_at_utc=decided_at_utc,
            decision_code=decision_code,
        )

    def expire(
        self,
        *,
        decided_at_utc: datetime,
        decision_code: str = "expired",
    ) -> AgentResult:
        return self._decide(
            status=AgentResultStatus.EXPIRED,
            decided_at_utc=decided_at_utc,
            decision_code=decision_code,
        )

    def _decide(
        self,
        *,
        status: AgentResultStatus,
        decided_at_utc: datetime,
        decision_code: str,
    ) -> AgentResult:
        if self.status is not AgentResultStatus.PENDING:
            raise DomainInvariantError("an AgentResult can be decided only once")
        return replace(
            self,
            status=status,
            decision_code=require_non_empty(decision_code, "decision_code"),
            decided_at_utc=require_utc(decided_at_utc, "decided_at_utc"),
        )


@dataclass(frozen=True, slots=True)
class BubbleDraft:
    """One deterministic role-message candidate from an approved result."""

    result_id: UUID
    bubble_index: int
    text: str
    images: tuple[str, ...] = ()
    reply_to_message_id: UUID | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.result_id, UUID):
            raise DomainInvariantError("result_id must be a UUID")
        object.__setattr__(
            self,
            "bubble_index",
            require_sequence(self.bubble_index, "bubble_index", minimum=0),
        )
        object.__setattr__(self, "text", require_non_empty(self.text, "text"))
        object.__setattr__(self, "images", tuple(self.images))
        if self.reply_to_message_id is not None and not isinstance(self.reply_to_message_id, UUID):
            raise DomainInvariantError("reply_to_message_id must be a UUID or None")


def project_bubbles(
    result: AgentResult,
    texts: Sequence[str],
    *,
    images: tuple[str, ...] = (),
    reply_to_message_id: UUID | None = None,
) -> tuple[BubbleDraft, ...]:
    """Project ordered bubbles after a result has been approved.

    The current caller passes one text.  A later sentence-splitting strategy can
    pass several texts without changing the persistence relationship.
    """

    if result.status is not AgentResultStatus.APPROVED:
        raise DomainInvariantError("only an approved result can produce bubbles")
    return tuple(
        BubbleDraft(
            result_id=result.result_id,
            bubble_index=index,
            text=text,
            images=images,
            reply_to_message_id=reply_to_message_id,
        )
        for index, text in enumerate(texts)
    )
