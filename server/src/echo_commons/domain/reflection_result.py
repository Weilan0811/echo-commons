from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime
from enum import StrEnum
from uuid import UUID

from echo_commons.domain.errors import (
    DomainInvariantError,
    optional_utc,
    require_non_empty,
    require_utc,
)


class GraphReviewStatus(StrEnum):
    """Decision state of the one review record attached to a graph."""

    PENDING = "pending"
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
    SKIPPED = "skipped"


@dataclass(frozen=True, slots=True)
class GraphReviewRecord:
    """Stored aggregate payload and its Runtime review decision."""

    result_id: UUID
    graph_run_id: UUID
    aggregate_fingerprint: str
    payload_json: str
    created_at_utc: datetime
    status: GraphReviewStatus | str = GraphReviewStatus.PENDING
    decision_code: str | None = None
    decided_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in ("result_id", "graph_run_id"):
            if not isinstance(getattr(self, field_name), UUID):
                raise DomainInvariantError(f"{field_name} must be a UUID")
        for field_name in ("aggregate_fingerprint", "payload_json"):
            object.__setattr__(
                self,
                field_name,
                require_non_empty(getattr(self, field_name), field_name),
            )
        try:
            json.loads(self.payload_json)
        except json.JSONDecodeError as exc:
            raise DomainInvariantError("payload_json must contain valid JSON") from exc
        object.__setattr__(self, "status", GraphReviewStatus(self.status))
        created = require_utc(self.created_at_utc, "created_at_utc")
        decided = optional_utc(self.decided_at_utc, "decided_at_utc")
        if self.status is GraphReviewStatus.PENDING:
            if self.decision_code is not None or decided is not None:
                raise DomainInvariantError("pending graph review cannot have a decision")
        elif decided is None or self.decision_code is None:
            raise DomainInvariantError("decided graph review needs a code and time")
        if self.decision_code is not None:
            object.__setattr__(
                self,
                "decision_code",
                require_non_empty(self.decision_code, "decision_code"),
            )
        if decided is not None and decided < created:
            raise DomainInvariantError("decided_at_utc must not precede created_at_utc")
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "decided_at_utc", decided)

    def decide(
        self,
        *,
        status: GraphReviewStatus,
        decided_at_utc: datetime,
        decision_code: str,
    ) -> GraphReviewRecord:
        if self.status is not GraphReviewStatus.PENDING:
            raise DomainInvariantError("a graph review can be decided only once")
        return replace(
            self,
            status=GraphReviewStatus(status),
            decision_code=require_non_empty(decision_code, "decision_code"),
            decided_at_utc=require_utc(decided_at_utc, "decided_at_utc"),
        )


__all__ = ["GraphReviewRecord", "GraphReviewStatus"]
