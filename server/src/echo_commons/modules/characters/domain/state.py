from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, field_validator


class StateKind(StrEnum):
    PHYSICAL = "physical"
    MOOD = "mood"
    ACTIVITY = "activity"


class InitialState(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    physical: str = Field(default="无明显不适", min_length=1, max_length=1000)
    mood: str = Field(default="平和", min_length=1, max_length=1000)
    activity: str = Field(default="空闲", min_length=1, max_length=1000)

    @field_validator("physical", "mood", "activity")
    @classmethod
    def nonblank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("Initial state must be nonempty")
        return value.strip()


@dataclass(frozen=True, slots=True)
class StateEntry:
    entry_id: str
    community_id: str
    character_id: str
    state_kind: StateKind
    value: str
    source_kind: str
    source_ref: str
    state_version: int
    recorded_at_utc: datetime
    expires_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "state_kind", StateKind(self.state_kind))
        if self.state_version < 1:
            raise ValueError("State version starts at 1")
        for value in (
            self.entry_id,
            self.community_id,
            self.character_id,
            self.source_kind,
            self.source_ref,
        ):
            if not value.strip():
                raise ValueError("State identity and source must be nonempty")
        if self.recorded_at_utc.tzinfo is None:
            raise ValueError("State time must include timezone")
        if self.expires_at_utc is not None and self.expires_at_utc <= self.recorded_at_utc:
            raise ValueError("State expiration must follow recording time")

    def effective(self, at: datetime) -> bool:
        return self.recorded_at_utc <= at and (
            self.expires_at_utc is None or at < self.expires_at_utc
        )
