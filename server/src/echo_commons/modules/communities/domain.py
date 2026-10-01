from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from zoneinfo import ZoneInfo


class CommunityStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class Community:
    community_id: str
    name: str
    timezone: str
    world_time_utc: datetime
    status: CommunityStatus
    state_version: int
    created_at_utc: datetime
    updated_at_utc: datetime

    def __post_init__(self) -> None:
        if not self.community_id.strip() or not self.name.strip():
            raise ValueError("Community ID and name must be nonempty")
        ZoneInfo(self.timezone)
        object.__setattr__(self, "status", CommunityStatus(self.status))
        if self.world_time_utc.tzinfo is None or self.state_version < 0:
            raise ValueError("Community time and state version are invalid")


@dataclass(frozen=True, slots=True)
class Player:
    player_id: str
    display_name: str
    created_at_utc: datetime

    def __post_init__(self) -> None:
        if not self.player_id.strip() or not self.display_name.strip():
            raise ValueError("Player ID and display name must be nonempty")
