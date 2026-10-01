from __future__ import annotations

import hashlib
from dataclasses import dataclass
from datetime import date, datetime
from enum import StrEnum
from uuid import UUID

from echo_commons.domain.errors import (
    DomainInvariantError,
    optional_utc,
    require_non_empty,
    require_sequence,
    require_utc,
)


class MemoryKind(StrEnum):
    FACT = "fact"
    EVENT = "event"
    PREFERENCE = "preference"
    PROMISE = "promise"
    THREAD = "thread"
    OTHER = "other"


class MemoryVisibility(StrEnum):
    RESIDENT = "resident"
    RECALLABLE = "recallable"
    PRIVATE = "private"


class MemorySegmentStatus(StrEnum):
    SEALED = "sealed"
    INGESTED = "ingested"


class MemoryViewKind(StrEnum):
    """Small derived prompt views maintained by Reflection."""

    CORE_MEMORY = "core_memory"
    STATE_SUMMARY = "state_summary"


def require_game_day(value: str, field_name: str = "game_day") -> str:
    """Require the stable ISO date key used by daily private records."""

    text = require_non_empty(value, field_name)
    try:
        date.fromisoformat(text)
    except ValueError as exc:
        raise DomainInvariantError(f"{field_name} must be an ISO date") from exc
    return text


def require_ratio(value: float, field_name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise DomainInvariantError(f"{field_name} must be a number between 0 and 1")
    numeric = float(value)
    if not 0.0 <= numeric <= 1.0:
        raise DomainInvariantError(f"{field_name} must be a number between 0 and 1")
    return numeric


@dataclass(frozen=True, slots=True)
class MemorySegment:
    """A sealed source window; message text remains owned by ``messages``."""

    segment_id: UUID
    account_id: str
    conversation_id: str
    character_id: str
    first_message_sequence: int
    last_message_sequence: int
    status: MemorySegmentStatus | str
    source_version: str
    sealed_at_utc: datetime
    created_at_utc: datetime
    updated_at_utc: datetime
    summary_text: str | None = None
    ingested_at_utc: datetime | None = None
    summary_version: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.segment_id, UUID):
            raise DomainInvariantError("segment_id must be a UUID")
        for field_name in (
            "account_id",
            "conversation_id",
            "character_id",
            "source_version",
        ):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        first = require_sequence(self.first_message_sequence, "first_message_sequence", minimum=1)
        last = require_sequence(self.last_message_sequence, "last_message_sequence", minimum=1)
        if last < first:
            raise DomainInvariantError(
                "last_message_sequence must not precede first_message_sequence"
            )
        object.__setattr__(self, "first_message_sequence", first)
        object.__setattr__(self, "last_message_sequence", last)
        object.__setattr__(self, "status", MemorySegmentStatus(self.status))
        sealed = require_utc(self.sealed_at_utc, "sealed_at_utc")
        created = require_utc(self.created_at_utc, "created_at_utc")
        updated = require_utc(self.updated_at_utc, "updated_at_utc")
        ingested = optional_utc(self.ingested_at_utc, "ingested_at_utc")
        if updated < created:
            raise DomainInvariantError("updated_at_utc must not precede created_at_utc")
        if sealed < created:
            raise DomainInvariantError("sealed_at_utc must not precede created_at_utc")
        if self.status is MemorySegmentStatus.SEALED and ingested is not None:
            raise DomainInvariantError("a sealed segment cannot have ingested_at_utc")
        if self.status is MemorySegmentStatus.INGESTED:
            if ingested is None:
                raise DomainInvariantError("an ingested segment requires ingested_at_utc")
            if ingested < sealed:
                raise DomainInvariantError("ingested_at_utc must not precede sealed_at_utc")
        object.__setattr__(self, "sealed_at_utc", sealed)
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "updated_at_utc", updated)
        object.__setattr__(self, "ingested_at_utc", ingested)
        if self.summary_text is not None:
            object.__setattr__(self, "summary_text", self.summary_text.strip() or None)
        if self.summary_version is not None:
            require_non_empty(self.summary_version, "summary_version")
            if not self.summary_text:
                raise DomainInvariantError("summary_version requires summary_text")


@dataclass(frozen=True, slots=True)
class MemoryEntry:
    """One independently recallable long-term memory page."""

    account_id: str
    character_id: str
    memory_id: str
    memory_kind: MemoryKind | str
    content: str
    source_kind: str
    source_ref: str
    subject_kind: str
    subject_id: str
    visibility: MemoryVisibility | str
    content_version: str
    recorded_at_utc: datetime
    confidence: float = 1.0
    salience: float = 0.5
    occurred_at_utc: datetime | None = None
    expires_at_utc: datetime | None = None
    invalidated_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "account_id",
            "character_id",
            "memory_id",
            "content",
            "source_kind",
            "source_ref",
            "subject_kind",
            "subject_id",
            "content_version",
        ):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "memory_kind", MemoryKind(self.memory_kind))
        object.__setattr__(self, "visibility", MemoryVisibility(self.visibility))
        object.__setattr__(self, "confidence", require_ratio(self.confidence, "confidence"))
        object.__setattr__(self, "salience", require_ratio(self.salience, "salience"))
        recorded = require_utc(self.recorded_at_utc, "recorded_at_utc")
        occurred = optional_utc(self.occurred_at_utc, "occurred_at_utc")
        expires = optional_utc(self.expires_at_utc, "expires_at_utc")
        invalidated = optional_utc(self.invalidated_at_utc, "invalidated_at_utc")
        if expires is not None and expires <= recorded:
            raise DomainInvariantError("expires_at_utc must be later than recorded_at_utc")
        if invalidated is not None and invalidated < recorded:
            raise DomainInvariantError("invalidated_at_utc must not precede recorded_at_utc")
        object.__setattr__(self, "recorded_at_utc", recorded)
        object.__setattr__(self, "occurred_at_utc", occurred)
        object.__setattr__(self, "expires_at_utc", expires)
        object.__setattr__(self, "invalidated_at_utc", invalidated)

    def is_active_at(self, now_utc: datetime) -> bool:
        now = require_utc(now_utc, "now_utc")
        return self.invalidated_at_utc is None and (
            self.expires_at_utc is None or now < self.expires_at_utc
        )


@dataclass(frozen=True, slots=True)
class DiaryEntry:
    """A permanent private character diary entry."""

    diary_id: UUID
    account_id: str
    character_id: str
    game_day: str
    content: str
    source_window_kind: str
    source_window_ref: str
    content_version: str
    created_at_utc: datetime

    def __post_init__(self) -> None:
        if not isinstance(self.diary_id, UUID):
            raise DomainInvariantError("diary_id must be a UUID")
        for field_name in (
            "account_id",
            "character_id",
            "content",
            "source_window_kind",
            "source_window_ref",
            "content_version",
        ):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "game_day", require_game_day(self.game_day))
        object.__setattr__(
            self, "created_at_utc", require_utc(self.created_at_utc, "created_at_utc")
        )


@dataclass(frozen=True, slots=True)
class Thought:
    """Private, temporary material produced by one approved conversation result."""

    thought_id: UUID
    result_id: UUID
    conversation_id: str
    account_id: str
    character_id: str
    game_day: str
    content: str
    created_at_utc: datetime

    segment_id: UUID | None = None

    @property
    def content_version(self) -> str:
        return hashlib.sha256(self.content.encode()).hexdigest()

    def __post_init__(self) -> None:
        require_non_empty(self.conversation_id, "conversation_id")
        if self.segment_id is not None and not isinstance(self.segment_id, UUID):
            raise DomainInvariantError("segment_id must be a UUID")
        if not isinstance(self.thought_id, UUID) or not isinstance(self.result_id, UUID):
            raise DomainInvariantError("thought_id and result_id must be UUIDs")
        for field_name in ("account_id", "character_id", "content"):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "game_day", require_game_day(self.game_day))
        object.__setattr__(
            self, "created_at_utc", require_utc(self.created_at_utc, "created_at_utc")
        )


@dataclass(frozen=True, slots=True)
class MemoryView:
    """One replaceable, source-backed character view for prompt projection."""

    account_id: str
    character_id: str
    view_kind: MemoryViewKind | str
    content: str
    source_refs: tuple[str, ...]
    content_version: str
    updated_at_utc: datetime

    def __post_init__(self) -> None:
        for field_name in ("account_id", "character_id", "content", "content_version"):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        object.__setattr__(self, "view_kind", MemoryViewKind(self.view_kind))
        refs = tuple(require_non_empty(ref, "source_ref") for ref in self.source_refs)
        if not refs or len(refs) != len(set(refs)):
            raise DomainInvariantError("memory view source_refs must be unique and non-empty")
        object.__setattr__(self, "source_refs", refs)
        object.__setattr__(
            self, "updated_at_utc", require_utc(self.updated_at_utc, "updated_at_utc")
        )


@dataclass(frozen=True, slots=True)
class MemoryEntity:
    """One canonical node in the rebuildable memory graph."""

    account_id: str
    character_id: str
    entity_id: str
    entity_kind: str
    canonical_name: str
    created_at_utc: datetime
    updated_at_utc: datetime
    invalidated_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        for field_name in (
            "account_id",
            "character_id",
            "entity_id",
            "entity_kind",
            "canonical_name",
        ):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        created = require_utc(self.created_at_utc, "created_at_utc")
        updated = require_utc(self.updated_at_utc, "updated_at_utc")
        invalidated = optional_utc(self.invalidated_at_utc, "invalidated_at_utc")
        if updated < created:
            raise DomainInvariantError("updated_at_utc must not precede created_at_utc")
        if invalidated is not None and invalidated < created:
            raise DomainInvariantError("invalidated_at_utc must not precede created_at_utc")
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "updated_at_utc", updated)
        object.__setattr__(self, "invalidated_at_utc", invalidated)


@dataclass(frozen=True, slots=True)
class MemoryEntityAlias:
    """A normalized lookup alias for one graph entity."""

    alias_id: UUID
    account_id: str
    character_id: str
    entity_id: str
    alias_text: str
    normalized_alias: str
    created_at_utc: datetime
    invalidated_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.alias_id, UUID):
            raise DomainInvariantError("alias_id must be a UUID")
        for field_name in (
            "account_id",
            "character_id",
            "entity_id",
            "alias_text",
            "normalized_alias",
        ):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        created = require_utc(self.created_at_utc, "created_at_utc")
        invalidated = optional_utc(self.invalidated_at_utc, "invalidated_at_utc")
        if invalidated is not None and invalidated < created:
            raise DomainInvariantError("invalidated_at_utc must not precede created_at_utc")
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "invalidated_at_utc", invalidated)


@dataclass(frozen=True, slots=True)
class MemoryEntryEntityLink:
    """A rebuildable page-to-entity association."""

    account_id: str
    character_id: str
    memory_id: str
    entity_id: str
    role: str
    created_at_utc: datetime

    def __post_init__(self) -> None:
        for field_name in (
            "account_id",
            "character_id",
            "memory_id",
            "entity_id",
            "role",
        ):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        object.__setattr__(
            self, "created_at_utc", require_utc(self.created_at_utc, "created_at_utc")
        )


@dataclass(frozen=True, slots=True)
class MemoryEdge:
    """A source-backed edge between two graph entities."""

    edge_id: UUID
    account_id: str
    character_id: str
    from_entity_id: str
    to_entity_id: str
    edge_kind: str
    confidence: float
    created_at_utc: datetime
    source_memory_id: str | None = None
    invalidated_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.edge_id, UUID):
            raise DomainInvariantError("edge_id must be a UUID")
        for field_name in (
            "account_id",
            "character_id",
            "from_entity_id",
            "to_entity_id",
            "edge_kind",
        ):
            object.__setattr__(
                self, field_name, require_non_empty(getattr(self, field_name), field_name)
            )
        if self.source_memory_id is not None:
            object.__setattr__(
                self,
                "source_memory_id",
                require_non_empty(self.source_memory_id, "source_memory_id"),
            )
        object.__setattr__(self, "confidence", require_ratio(self.confidence, "confidence"))
        created = require_utc(self.created_at_utc, "created_at_utc")
        invalidated = optional_utc(self.invalidated_at_utc, "invalidated_at_utc")
        if invalidated is not None and invalidated < created:
            raise DomainInvariantError("invalidated_at_utc must not precede created_at_utc")
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "invalidated_at_utc", invalidated)


__all__ = [
    "DiaryEntry",
    "MemoryEdge",
    "MemoryEntity",
    "MemoryEntityAlias",
    "MemoryEntry",
    "MemoryEntryEntityLink",
    "MemoryKind",
    "MemorySegment",
    "MemorySegmentStatus",
    "MemoryView",
    "MemoryViewKind",
    "MemoryVisibility",
    "Thought",
    "require_game_day",
    "require_ratio",
]
