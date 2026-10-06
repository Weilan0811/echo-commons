from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from echo_commons.shared.errors import CharacterNotReady


class MemoryMode(StrEnum):
    SIMPLE = "simple"
    FULL = "full"


class MemoryStatus(StrEnum):
    PREPARING = "preparing"
    READY = "ready"
    FAILED = "failed"


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
    memory_mode: MemoryMode = MemoryMode.FULL
    memory_status: MemoryStatus = MemoryStatus.READY
    memory_error_code: str | None = None
    memory_phase: str | None = None

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
        object.__setattr__(self, "memory_mode", MemoryMode(self.memory_mode))
        object.__setattr__(self, "memory_status", MemoryStatus(self.memory_status))
        if self.availability_version < 0:
            raise ValueError("Availability version must be nonnegative")

    def require_ready(self) -> None:
        if self.memory_status is not MemoryStatus.READY:
            raise CharacterNotReady("角色记忆尚未准备完成，请查看准备状态或重试。")
