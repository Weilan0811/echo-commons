from __future__ import annotations

from dataclasses import dataclass
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


class CharacterStateKind(StrEnum):
    PHYSICAL = "physical"
    MOOD = "mood"
    ACTIVITY = "activity"


@dataclass(frozen=True, slots=True)
class CharacterStateEntry:
    """One historical state value; the newest version is the current value."""

    entry_id: UUID
    character_id: str
    state_kind: CharacterStateKind | str
    value: str
    source_kind: str
    source_ref: str
    state_version: int
    recorded_at_utc: datetime
    expires_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.entry_id, UUID):
            raise DomainInvariantError("entry_id must be a UUID")
        for field_name in ("character_id", "value", "source_kind", "source_ref"):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "state_kind", CharacterStateKind(self.state_kind))
        object.__setattr__(
            self,
            "state_version",
            require_sequence(self.state_version, "state_version"),
        )
        recorded = require_utc(self.recorded_at_utc, "recorded_at_utc")
        expires = optional_utc(self.expires_at_utc, "expires_at_utc")
        if expires is not None and expires <= recorded:
            raise DomainInvariantError("expires_at_utc must be later than recorded_at_utc")
        object.__setattr__(self, "recorded_at_utc", recorded)
        object.__setattr__(self, "expires_at_utc", expires)

    def is_unexpired_at(self, now_utc: datetime) -> bool:
        now = require_utc(now_utc, "now_utc")
        return self.recorded_at_utc <= now and (
            self.expires_at_utc is None or now < self.expires_at_utc
        )


def replace_character_state_entry(
    previous: CharacterStateEntry | None,
    *,
    entry_id: UUID,
    character_id: str,
    state_kind: CharacterStateKind | str,
    value: str,
    source_kind: str,
    source_ref: str,
    expected_version: int,
    recorded_at_utc: datetime,
    expires_at_utc: datetime | None = None,
) -> CharacterStateEntry:
    """Append a new value for one category after checking its current version."""

    version = require_sequence(expected_version, "expected_version", minimum=0)
    observed_version = previous.state_version if previous is not None else 0
    if version != observed_version:
        raise DomainInvariantError(
            f"character state version conflict: expected {version}, found {observed_version}"
        )
    current = CharacterStateEntry(
        entry_id=entry_id,
        character_id=character_id,
        state_kind=state_kind,
        value=value,
        source_kind=source_kind,
        source_ref=source_ref,
        state_version=observed_version + 1,
        recorded_at_utc=recorded_at_utc,
        expires_at_utc=expires_at_utc,
    )
    if previous is not None and (
        previous.character_id != current.character_id
        or previous.state_kind is not current.state_kind
    ):
        raise DomainInvariantError("previous state entry belongs to a different state slot")
    return current


__all__ = [
    "CharacterStateEntry",
    "CharacterStateKind",
    "replace_character_state_entry",
]
