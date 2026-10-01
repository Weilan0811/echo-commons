from __future__ import annotations

from datetime import datetime
from typing import Protocol

import aiosqlite

from echo_commons.agents.contracts import (
    CharacterStateSnapshot,
    ContextSourceSnapshot,
    MemoryContext,
    MemoryItem,
    RelationshipStateSnapshot,
    SituationView,
    SnapshotSourceVersion,
)
from echo_commons.agents.contracts.context import SegmentSummary, SessionDigest
from echo_commons.domain.character_state_entry import CharacterStateEntry, CharacterStateKind
from echo_commons.domain.memory import MemoryViewKind
from echo_commons.domain.relationship import (
    RelationshipKey,
    RelationshipState,
    RelationshipTargetKind,
)
from echo_commons.domain.state import CharacterState
from echo_commons.domain.task import ConversationTask
from echo_commons.store.memory_provenance import MemoryProvenanceRepository
from echo_commons.store.memory_repositories import MemoryEntryRepository, MemoryViewRepository
from echo_commons.store.repository_support import parse_time
from echo_commons.store.runtime_repositories import (
    CharacterStateRepository,
    WorldStateRepository,
)
from echo_commons.store.state_repositories import (
    CharacterStateEntryRepository,
    RelationshipStateRepository,
)


class ContextSnapshotSource(Protocol):
    """Supply request-time state without owning the Runtime transaction."""

    async def load(
        self,
        task: ConversationTask,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection,
    ) -> ContextSourceSnapshot:
        """Read all optional state and memory sources for one immutable snapshot."""


class EmptyContextSource:
    """Safe baseline used by isolated builders and older callers."""

    async def load(
        self,
        task: ConversationTask,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection,
    ) -> ContextSourceSnapshot:
        del connection
        return ContextSourceSnapshot(
            character_state=CharacterStateSnapshot(
                character_id=task.character_id,
                availability_updated_at_utc=now_utc,
            ),
            relationship_state=RelationshipStateSnapshot(subject_id=task.account_id),
        )


class RepositoryContextSource:
    """Project authoritative world, self-state and relationship rows into V2."""

    def __init__(
        self,
        world_states: WorldStateRepository,
        character_states: CharacterStateRepository,
        character_state_entries: CharacterStateEntryRepository,
        relationship_states: RelationshipStateRepository,
        memory_entries: MemoryEntryRepository | None = None,
        resident_memory_limit: int = 32,
    ) -> None:
        self.world_states = world_states
        self.character_states = character_states
        self.character_state_entries = character_state_entries
        self.relationship_states = relationship_states
        self.memory_entries = memory_entries
        self.resident_memory_limit = resident_memory_limit

    async def load(
        self,
        task: ConversationTask,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection,
    ) -> ContextSourceSnapshot:
        return await self.load_character(
            task.account_id,
            task.character_id,
            now_utc=now_utc,
            memory_limit=self.resident_memory_limit,
            connection=connection,
        )

    async def load_character(
        self,
        account_id: str,
        character_id: str,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection,
        memory_limit: int = 32,
    ) -> ContextSourceSnapshot:
        """Project state for reflection without constructing a chat task."""
        world_state = await self.world_states.get(connection=connection)
        character_state = await self.character_states.get(
            character_id,
            connection=connection,
        )
        state_entries = await self.character_state_entries.list_latest_for_character(
            character_id,
            connection=connection,
        )
        relationship_key = RelationshipKey(
            account_id=account_id,
            observer_character_id=character_id,
            target_kind=RelationshipTargetKind.ACCOUNT,
            target_id=account_id,
        )
        relationship_state = await self.relationship_states.get(
            relationship_key,
            connection=connection,
        )
        projected_character = _character_snapshot(
            character_state,
            state_entries=state_entries,
            character_id=character_id,
            now_utc=now_utc,
        )
        source_versions = [
            SnapshotSourceVersion(
                source="character_availability",
                version=str(projected_character.availability_version),
            )
        ]
        latest_by_kind = {entry.state_kind: entry for entry in state_entries}
        for kind in CharacterStateKind:
            entry = latest_by_kind.get(kind)
            source_versions.append(
                SnapshotSourceVersion(
                    source=f"character_state.{kind.value}",
                    version=str(entry.state_version if entry is not None else 0),
                )
            )
        projected_relationship = _relationship_snapshot(
            relationship_state,
            key=relationship_key,
            subject_id=account_id,
            now_utc=now_utc,
        )
        source_versions.append(
            SnapshotSourceVersion(
                source="relationship_state",
                version=str(projected_relationship.state_version),
            )
        )
        memory_items: tuple[MemoryItem, ...] = ()
        memory_version = "empty"
        if self.memory_entries is not None:
            resident_entries, memory_version = await self.memory_entries.list_resident(
                account_id,
                character_id,
                now_utc=now_utc,
                limit=memory_limit,
                connection=connection,
            )
            memory_items = tuple(
                MemoryItem(
                    memory_id=entry.memory_id,
                    content_version=entry.content_version,
                    summary=entry.content,
                    memory_kind=entry.memory_kind.value,
                    confidence=entry.confidence,
                    salience=entry.salience,
                    source=entry.source_kind,
                    occurred_at_utc=entry.occurred_at_utc,
                    updated_at_utc=entry.recorded_at_utc,
                )
                for entry in resident_entries
            )
            source_versions.append(
                SnapshotSourceVersion(source="memory.resident", version=memory_version)
            )
        if world_state is None:
            situation = SituationView()
        else:
            situation = SituationView(
                world_phase=world_state.phase,
                stage_summary=world_state.phase,
                world_time_utc=world_state.world_time_utc,
            )
            source_versions.append(
                SnapshotSourceVersion(
                    source="world_state",
                    version=str(world_state.state_version),
                )
            )
        views = {}
        if self.memory_entries is not None:
            repository = MemoryViewRepository(self.memory_entries.database)
            for kind in MemoryViewKind:
                view = await repository.get_valid(
                    account_id, character_id, kind, now_utc=now_utc, connection=connection
                )
                if view is None:
                    continue
                views[kind.value] = MemoryItem(
                    memory_id=f"view:{kind.value}",
                    content_version=view.content_version,
                    summary=view.content,
                    source="memory_view",
                    updated_at_utc=view.updated_at_utc,
                )
                source_versions.append(
                    SnapshotSourceVersion(
                        source=f"memory.view.{kind.value}", version=view.content_version
                    )
                )
        return ContextSourceSnapshot(
            character_state=projected_character,
            relationship_state=projected_relationship,
            memory_context=MemoryContext(
                core_memory=views.get("core_memory"),
                state_summary=views.get("state_summary"),
                resident=memory_items,
                resident_version=memory_version,
            ),
            active_threads=(),
            situation=situation,
            source_versions=tuple(source_versions),
        )

    async def load_continuity(
        self, task: ConversationTask, *, through_sequence: int, connection: aiosqlite.Connection
    ) -> tuple[SessionDigest | None, tuple[SegmentSummary, ...]]:
        digest = await MemoryProvenanceRepository().latest_digest(
            task.account_id,
            task.conversation_id,
            task.character_id,
            through_sequence=through_sequence,
            connection=connection,
        )
        projected = (
            SessionDigest(
                digest_id=digest["digest_id"],
                content=digest["content"],
                covers_through_sequence=digest["covers_through_sequence"],
                content_version=digest["content_version"],
                created_at_utc=parse_time(digest["created_at_utc"]),
            )
            if digest
            else None
        )
        segments = await MemoryProvenanceRepository().list_context_summaries(
            task.account_id,
            task.conversation_id,
            task.character_id,
            after_sequence=projected.covers_through_sequence if projected else 0,
            through_sequence=through_sequence,
            connection=connection,
        )
        summaries = []
        used = 0
        for row in segments:
            if used + len(row["summary_text"]) > 8000:
                break
            used += len(row["summary_text"])
            summaries.append(
                SegmentSummary(
                    segment_id=row["segment_id"],
                    content=row["summary_text"],
                    content_version=row["summary_version"],
                    first_message_sequence=row["first_message_sequence"],
                    last_message_sequence=row["last_message_sequence"],
                )
            )
        return projected, tuple(reversed(summaries))


def _character_snapshot(
    state: CharacterState | None,
    *,
    state_entries: tuple[CharacterStateEntry, ...],
    character_id: str,
    now_utc: datetime,
) -> CharacterStateSnapshot:
    current = {
        entry.state_kind: entry.value for entry in state_entries if entry.is_unexpired_at(now_utc)
    }
    if state is None:
        return CharacterStateSnapshot(
            character_id=character_id,
            physical_condition=current.get(CharacterStateKind.PHYSICAL, ""),
            mood=current.get(CharacterStateKind.MOOD, ""),
            current_activity=current.get(CharacterStateKind.ACTIVITY, ""),
            availability_updated_at_utc=now_utc,
        )
    return CharacterStateSnapshot(
        character_id=state.character_id,
        availability_version=state.state_version,
        availability_status=state.availability_status.value,
        availability_reason=state.reason_code,
        next_check_at_utc=state.next_check_at_utc,
        physical_condition=current.get(CharacterStateKind.PHYSICAL, ""),
        mood=current.get(CharacterStateKind.MOOD, ""),
        current_activity=current.get(CharacterStateKind.ACTIVITY, ""),
        availability_updated_at_utc=state.updated_at_utc,
    )


def _relationship_snapshot(
    state: RelationshipState | None,
    *,
    key: RelationshipKey,
    subject_id: str,
    now_utc: datetime,
) -> RelationshipStateSnapshot:
    projected = state or RelationshipState.stranger(key, updated_at_utc=now_utc)
    values = projected.values
    return RelationshipStateSnapshot(
        subject_id=subject_id,
        state_version=projected.state_version,
        relationship_type=projected.relationship_type.value,
        affection=values.affection if values is not None else None,
        trust=values.trust if values is not None else None,
        attachment=values.attachment if values is not None else None,
        attitude_summary=projected.attitude_summary,
        updated_at_utc=projected.updated_at_utc,
    )


__all__ = ["ContextSnapshotSource", "EmptyContextSource", "RepositoryContextSource"]
