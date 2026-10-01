from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class TurnStatus(StrEnum):
    RUNNING = "running"
    COMPLETED = "completed"
    CANCELLED = "cancelled"


class ParticipationStatus(StrEnum):
    SILENT = "silent"
    SELECTED = "selected"
    COMPLETED = "completed"
    FAILED = "failed"
    CANCELLED = "cancelled"


@dataclass(frozen=True, slots=True)
class ParticipationDecision:
    social_turn_id: str
    character_id: str
    reason_code: str
    selection_order: int | None
    status: ParticipationStatus
    outcome: str | None
    updated_at_utc: datetime

    def __post_init__(self) -> None:
        object.__setattr__(self, "status", ParticipationStatus(self.status))
        if self.status is ParticipationStatus.SILENT:
            valid = self.selection_order is None and self.outcome == "silent"
        elif self.status is ParticipationStatus.SELECTED:
            valid = self.selection_order is not None and self.outcome is None
        elif self.status is ParticipationStatus.COMPLETED:
            valid = self.selection_order is not None and self.outcome in ("message", "silent")
        else:
            valid = self.selection_order is not None and self.outcome == self.status.value
        if not valid or (self.selection_order is not None and self.selection_order < 0):
            raise ValueError("Participation state, outcome and order are inconsistent")


@dataclass(frozen=True, slots=True)
class SocialTurn:
    social_turn_id: str
    community_id: str
    conversation_id: str
    audience: tuple[str, ...]
    visibility: str
    observation_max_sequence: int
    membership_version: int
    status: TurnStatus
    created_at_utc: datetime
    completed_at_utc: datetime | None
