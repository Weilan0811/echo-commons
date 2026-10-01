from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum


class AvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    OFFLINE = "offline"
    BUSY = "busy"


@dataclass(frozen=True, slots=True)
class CharacterInstance:
    character_id: str
    community_id: str
    blueprint_id: str
    blueprint_version: str
    availability_status: AvailabilityStatus
    availability_reason: str | None
    next_check_at_utc: datetime | None
    availability_version: int
    created_at_utc: datetime
    updated_at_utc: datetime

    def __post_init__(self) -> None:
        for value in (
            self.character_id,
            self.community_id,
            self.blueprint_id,
            self.blueprint_version,
        ):
            if not value.strip():
                raise ValueError("Character identity and blueprint references must be nonempty")
        object.__setattr__(
            self, "availability_status", AvailabilityStatus(self.availability_status)
        )
        if self.availability_version < 0:
            raise ValueError("Availability version must be nonnegative")
