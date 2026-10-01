"""World and character state used by deterministic response eligibility rules."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from echo_server.domain.errors import (
    DomainInvariantError,
    optional_utc,
    require_non_empty,
    require_sequence,
    require_utc,
)


class WorldStatus(StrEnum):
    ACTIVE = "active"
    PAUSED = "paused"


@dataclass(frozen=True, slots=True)
class WorldState:
    """The single authoritative world-state row projected into memory."""

    state_version: int
    world_time_utc: datetime
    updated_at_utc: datetime
    status: WorldStatus | str = WorldStatus.ACTIVE
    phase: str = ""

    def __post_init__(self) -> None:
        object.__setattr__(
            self,
            "state_version",
            require_sequence(self.state_version, "state_version", minimum=0),
        )
        object.__setattr__(self, "status", WorldStatus(self.status))
        if not isinstance(self.phase, str):
            raise DomainInvariantError("phase must be a string")
        world_time = require_utc(self.world_time_utc, "world_time_utc")
        updated = require_utc(self.updated_at_utc, "updated_at_utc")
        if updated < world_time:
            raise DomainInvariantError("updated_at_utc must not be earlier than world_time_utc")
        object.__setattr__(self, "world_time_utc", world_time)
        object.__setattr__(self, "updated_at_utc", updated)

    def advance(
        self,
        *,
        state_version: int,
        world_time_utc: datetime,
        updated_at_utc: datetime,
        status: WorldStatus | str | None = None,
        phase: str | None = None,
    ) -> WorldState:
        version = require_sequence(state_version, "state_version", minimum=0)
        if version <= self.state_version:
            raise DomainInvariantError("world state_version must increase")
        updated = require_utc(updated_at_utc, "updated_at_utc")
        if updated < self.updated_at_utc:
            raise DomainInvariantError("world state time cannot move backwards")
        return WorldState(
            state_version=version,
            world_time_utc=world_time_utc,
            updated_at_utc=updated,
            status=self.status if status is None else status,
            phase=self.phase if phase is None else phase,
        )


class CharacterAvailabilityStatus(StrEnum):
    AVAILABLE = "available"
    OFFLINE = "offline"
    BUSY = "busy"
    STORY_ABSENT = "story_absent"
    TECHNICAL_ERROR = "technical_error"


@dataclass(frozen=True, slots=True)
class CharacterState:
    """The current global reply availability of one character."""

    character_id: str
    availability_status: CharacterAvailabilityStatus | str
    state_version: int
    updated_at_utc: datetime
    reason_code: str | None = None
    next_check_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "character_id", require_non_empty(self.character_id, "character_id")
        )
        object.__setattr__(
            self,
            "availability_status",
            CharacterAvailabilityStatus(self.availability_status),
        )
        object.__setattr__(
            self,
            "state_version",
            require_sequence(self.state_version, "state_version", minimum=0),
        )
        if self.reason_code is not None:
            object.__setattr__(
                self, "reason_code", require_non_empty(self.reason_code, "reason_code")
            )
        updated = require_utc(self.updated_at_utc, "updated_at_utc")
        next_check = optional_utc(self.next_check_at_utc, "next_check_at_utc")
        object.__setattr__(self, "updated_at_utc", updated)
        object.__setattr__(self, "next_check_at_utc", next_check)

    @property
    def can_reply(self) -> bool:
        return self.availability_status is CharacterAvailabilityStatus.AVAILABLE

    def update(
        self,
        *,
        availability_status: CharacterAvailabilityStatus | str,
        state_version: int,
        updated_at_utc: datetime,
        reason_code: str | None = None,
        next_check_at_utc: datetime | None = None,
    ) -> CharacterState:
        version = require_sequence(state_version, "state_version", minimum=0)
        if version <= self.state_version:
            raise DomainInvariantError("character state_version must increase")
        updated = require_utc(updated_at_utc, "updated_at_utc")
        if updated < self.updated_at_utc:
            raise DomainInvariantError("character state time cannot move backwards")
        return CharacterState(
            character_id=self.character_id,
            availability_status=availability_status,
            state_version=version,
            updated_at_utc=updated,
            reason_code=reason_code,
            next_check_at_utc=next_check_at_utc,
        )


@dataclass(frozen=True, slots=True)
class EligibilityRequest:
    """The immutable state inputs for one response-eligibility evaluation."""

    world_state: WorldState
    character_state: CharacterState


@dataclass(frozen=True, slots=True)
class EligibilityDecision:
    """The stable, persistence-free result of eligibility evaluation."""

    allowed: bool
    reason_codes: tuple[str, ...]
    next_check_at_utc: datetime | None
    world_state_version: int
    character_state_version: int

    def __post_init__(self) -> None:
        if self.allowed and self.reason_codes:
            raise DomainInvariantError("an allowed decision cannot contain blocking reasons")
        if not self.allowed and not self.reason_codes:
            raise DomainInvariantError("a blocked decision must contain a reason")
        object.__setattr__(self, "reason_codes", tuple(self.reason_codes))
        object.__setattr__(
            self,
            "next_check_at_utc",
            optional_utc(self.next_check_at_utc, "next_check_at_utc"),
        )
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


def evaluate_response_eligibility(request: EligibilityRequest) -> EligibilityDecision:
    """Evaluate state gates without I/O or side effects."""

    reasons: list[str] = []
    if request.world_state.status is not WorldStatus.ACTIVE:
        reasons.append("world_unavailable")
    if not request.character_state.can_reply:
        reasons.append(f"character_{request.character_state.availability_status.value}")
    return EligibilityDecision(
        allowed=not reasons,
        reason_codes=tuple(reasons),
        next_check_at_utc=request.character_state.next_check_at_utc,
        world_state_version=request.world_state.state_version,
        character_state_version=request.character_state.state_version,
    )
