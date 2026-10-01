from __future__ import annotations

from collections.abc import Sequence
from datetime import datetime, timedelta
from typing import Protocol
from uuid import NAMESPACE_URL, uuid5

import aiosqlite

from echo_commons.agents.contracts.reflection_graph import GraphContextSnapshot
from echo_commons.domain.character_state_entry import (
    CharacterStateKind,
    replace_character_state_entry,
)
from echo_commons.domain.errors import DomainInvariantError
from echo_commons.domain.memory import (
    MemoryEdge,
    MemoryEntity,
    MemoryEntityAlias,
    MemoryEntry,
    MemoryEntryEntityLink,
    MemoryKind,
    MemorySegment,
    MemorySegmentStatus,
    MemoryVisibility,
)
from echo_commons.domain.memory_sources import MemorySourceRef, SummaryBatch
from echo_commons.domain.reflection_graph import ReflectionGraphRun, content_fingerprint
from echo_commons.domain.relationship import (
    RelationshipDimension,
    RelationshipDirection,
    RelationshipEvidence,
    RelationshipEvidenceKind,
    RelationshipImpact,
    RelationshipKey,
    RelationshipPolicy,
    RelationshipState,
    RelationshipTargetKind,
    RelationshipValues,
    apply_relationship_evidence,
)
from echo_commons.runtime.modules import ReflectionModule
from echo_commons.runtime.reflection.review import (
    ContinuityCompressionChangeSet,
    MemoryOrganizationChangeSet,
    ReviewedReflectionBatch,
    SegmentReflectionChangeSet,
)
from echo_commons.store.memory_provenance import MemoryProvenanceRepository


class ReflectionFactHandler(Protocol):
    async def apply(
        self,
        change_set: SegmentReflectionChangeSet,
        *,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        segment: MemorySegment,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> None: ...


class SegmentSummaryHandler:
    """Write the reviewed summary and exact source coverage."""

    def __init__(self, runtime: ReflectionModule) -> None:
        self.runtime = runtime

    async def apply(
        self,
        change_set: SegmentReflectionChangeSet,
        *,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        segment: MemorySegment,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> None:
        summary = change_set.summary
        if summary is None:
            return
        if segment.status is not MemorySegmentStatus.SEALED:
            raise DomainInvariantError("reflection_segment_not_sealed")
        if (
            summary.first_message_sequence != segment.first_message_sequence
            or summary.last_message_sequence != segment.last_message_sequence
        ):
            raise DomainInvariantError("segment summary boundary is stale")
        source = _segment_source(graph_run, segment)
        await _provenance_sources(segment, snapshot, connection)
        await self.runtime.memory_segments.update_summary(
            segment.segment_id,
            summary_text=summary.summary,
            expected_source_version=source.version,
            updated_at_utc=now,
            connection=connection,
        )
        sources = await MemoryProvenanceRepository().segment_sources(
            str(segment.segment_id), connection=connection
        )
        await MemoryProvenanceRepository().record_coverage(
            "segment_summary",
            str(segment.segment_id),
            sources,
            connection=connection,
        )


class RelationshipFactHandler:
    """Turn reviewed dimensions into Runtime-owned interaction evidence."""

    def __init__(self, runtime: ReflectionModule) -> None:
        self.runtime = runtime

    async def apply(
        self,
        change_set: SegmentReflectionChangeSet,
        *,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        segment: MemorySegment,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> None:
        runtime = self.runtime
        key = RelationshipKey(
            account_id=graph_run.account_id,
            observer_character_id=graph_run.character_id,
            target_kind=RelationshipTargetKind.ACCOUNT,
            target_id=graph_run.account_id,
        )
        for candidate in change_set.relationship_impacts:
            fingerprint = content_fingerprint(candidate.model_dump(mode="json")).value
            evidence_id = uuid5(
                NAMESPACE_URL,
                f"reflection-relationship:{graph_run.graph_run_id}:{fingerprint}",
            )
            evidence = RelationshipEvidence(
                evidence_id=evidence_id,
                key=key,
                evidence_kind=RelationshipEvidenceKind.INTERACTION,
                source_kind="reflection",
                source_ref=f"reflection:{graph_run.graph_run_id}:{fingerprint}",
                occurred_at_utc=_occurred_at(snapshot, candidate.source_refs, now),
                recorded_at_utc=now,
            )
            await runtime.relationship_evidence.ensure(evidence, connection=connection)
            current = await runtime.relationship_states.get(key, connection)
            state = current or RelationshipState.stranger(key, updated_at_utc=now)
            direction = {
                "positive": RelationshipDirection.UP,
                "negative": RelationshipDirection.DOWN,
                "neutral": RelationshipDirection.NEUTRAL,
            }[candidate.direction]
            transition = apply_relationship_evidence(
                state,
                evidence,
                (
                    RelationshipImpact(
                        evidence_id=evidence_id,
                        dimension=RelationshipDimension(candidate.dimension),
                        direction=direction,
                        magnitude=candidate.level,
                    ),
                ),
                _relationship_policy(),
                expected_version=state.state_version,
                updated_at_utc=now,
            )
            if transition.state_changed:
                await runtime.relationship_states.save(
                    transition.state,
                    expected_version=state.state_version,
                    connection=connection,
                )


class StateFactHandler:
    """Append reviewed character state with Runtime-owned expiry rules."""

    def __init__(self, runtime: ReflectionModule) -> None:
        self.runtime = runtime

    async def apply(
        self,
        change_set: SegmentReflectionChangeSet,
        *,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        segment: MemorySegment,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> None:
        runtime = self.runtime
        current_by_kind = {
            entry.state_kind: entry
            for entry in await runtime.character_state_entries.list_latest_for_character(
                graph_run.character_id,
                connection=connection,
            )
        }
        for candidate in change_set.state_entries:
            kind = CharacterStateKind(candidate.state_kind)
            previous = current_by_kind.get(kind)
            expected_version = previous.state_version if previous is not None else 0
            fingerprint = content_fingerprint(candidate.model_dump(mode="json")).value
            entry = replace_character_state_entry(
                previous,
                entry_id=uuid5(
                    NAMESPACE_URL,
                    f"reflection-state:{graph_run.graph_run_id}:{fingerprint}",
                ),
                character_id=graph_run.character_id,
                state_kind=kind,
                value=candidate.value.strip(),
                source_kind="reflection",
                source_ref=f"reflection:{graph_run.graph_run_id}:{fingerprint}",
                expected_version=expected_version,
                recorded_at_utc=now,
                expires_at_utc=(
                    now + timedelta(hours=24) if kind is CharacterStateKind.ACTIVITY else None
                ),
            )
            await runtime.character_state_entries.append(
                entry,
                expected_version=expected_version,
                connection=connection,
            )
            current_by_kind[kind] = entry


class FactHandlerRegistry:
    """Apply each fact family through its own small handler."""

    def __init__(
        self,
        runtime: ReflectionModule,
        handlers: Sequence[ReflectionFactHandler] | None = None,
    ) -> None:
        self.handlers = tuple(
            handlers
            or (
                SegmentSummaryHandler(runtime),
                RelationshipFactHandler(runtime),
                StateFactHandler(runtime),
            )
        )

    async def apply(
        self,
        change_set: SegmentReflectionChangeSet,
        *,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        segment: MemorySegment,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> None:
        for handler in self.handlers:
            await handler.apply(
                change_set,
                graph_run=graph_run,
                snapshot=snapshot,
                segment=segment,
                now=now,
                connection=connection,
            )


class ReflectionGraphCommitService:
    """Own Runtime-owned fact commits after review."""

    def __init__(
        self,
        runtime: ReflectionModule,
        registry: FactHandlerRegistry | None = None,
    ) -> None:
        self.runtime = runtime
        self.registry = registry or FactHandlerRegistry(runtime)
        self.memory_organization = MemoryOrganizationCommitService(runtime)

    async def commit(
        self,
        reviewed: ReviewedReflectionBatch,
        *,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        segment: MemorySegment,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> None:
        if not reviewed.approved:
            raise DomainInvariantError("only an approved ReflectionBatch can commit facts")
        change_set = reviewed.change_set
        if change_set is None:
            raise DomainInvariantError("approved ReflectionBatch has no ChangeSet")
        if not isinstance(change_set, SegmentReflectionChangeSet):
            raise DomainInvariantError("segment graph requires a segment ChangeSet")
        await self.registry.apply(
            change_set,
            graph_run=graph_run,
            snapshot=snapshot,
            segment=segment,
            now=now,
            connection=connection,
        )
        if segment.status is MemorySegmentStatus.SEALED:
            await self.runtime.memory_segments.mark_ingested(
                segment.segment_id,
                ingested_at_utc=now,
                updated_at_utc=now,
                connection=connection,
            )
        await MemoryProvenanceRepository().cleanup_thoughts(connection=connection)

    async def commit_memory_organization(
        self,
        reviewed: ReviewedReflectionBatch,
        *,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        summary_batch: SummaryBatch,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> None:
        await self.memory_organization.commit(
            reviewed,
            graph_run=graph_run,
            snapshot=snapshot,
            summary_batch=summary_batch,
            now=now,
            connection=connection,
        )

    async def commit_continuity_compression(
        self,
        reviewed: ReviewedReflectionBatch,
        *,
        snapshot: GraphContextSnapshot,
        summary_batch: SummaryBatch,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> None:
        if not reviewed.approved:
            raise DomainInvariantError("only an approved ReflectionBatch can commit continuity")
        change_set = reviewed.change_set
        if not isinstance(change_set, ContinuityCompressionChangeSet):
            raise DomainInvariantError("continuity graph requires a continuity ChangeSet")
        if change_set.batch_id != summary_batch.batch_id:
            raise DomainInvariantError("continuity compression batch identity changed")
        if (
            change_set.digest.covers_through_sequence
            != snapshot.context.window.last_message_sequence
        ):
            raise DomainInvariantError("continuity digest boundary is stale")
        await MemoryProvenanceRepository().commit_digest(
            summary_batch,
            change_set.digest.content,
            now_utc=now,
            connection=connection,
        )


class MemoryOrganizationCommitService:
    """审核通过后写入记忆页、实体、边和消费进度。"""

    def __init__(self, runtime: ReflectionModule) -> None:
        self.runtime = runtime
        self.provenance = MemoryProvenanceRepository()

    async def commit(
        self,
        reviewed: ReviewedReflectionBatch,
        *,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        summary_batch: SummaryBatch,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> None:
        if not reviewed.approved:
            raise DomainInvariantError("only an approved ReflectionBatch can commit memory")
        change_set = reviewed.change_set
        if not isinstance(change_set, MemoryOrganizationChangeSet):
            raise DomainInvariantError("memory graph requires a memory ChangeSet")
        if change_set.batch_id != summary_batch.batch_id:
            raise DomainInvariantError("memory organization batch identity changed")
        if not change_set.memory_entries and not change_set.entities and not change_set.edges:
            await self.provenance.commit_organization(
                summary_batch,
                outcome="no_op",
                now_utc=now,
                connection=connection,
            )
            return

        entity_ids = await self._write_entities(
            change_set,
            graph_run=graph_run,
            now=now,
            connection=connection,
        )
        memory_ids = await self._write_memory_entries(
            change_set,
            graph_run=graph_run,
            snapshot=snapshot,
            entity_ids=entity_ids,
            now=now,
            connection=connection,
        )
        await self._write_edges(
            change_set,
            graph_run=graph_run,
            entity_ids=entity_ids,
            memory_ids=memory_ids,
            now=now,
            connection=connection,
        )
        await self.provenance.commit_organization(
            summary_batch,
            outcome="completed",
            now_utc=now,
            connection=connection,
        )

    async def _write_entities(
        self,
        change_set: MemoryOrganizationChangeSet,
        *,
        graph_run: ReflectionGraphRun,
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> dict[str, str]:
        graph = self.runtime.memory.memory_graph
        resolved: dict[str, str] = {}
        for candidate in change_set.entities:
            normalized = _normalize_alias(candidate.canonical_name)
            existing = await graph.find_entity_by_alias(
                graph_run.account_id,
                graph_run.character_id,
                normalized,
                connection=connection,
            )
            if existing is not None:
                if existing.entity_kind != candidate.entity_kind:
                    raise DomainInvariantError("memory entity kind conflicts with existing alias")
                entity_id = existing.entity_id
            else:
                entity_id = str(
                    uuid5(
                        NAMESPACE_URL,
                        f"memory-entity:{graph_run.account_id}:{graph_run.character_id}:"
                        f"{candidate.entity_kind}:{normalized}",
                    )
                )
                entity = MemoryEntity(
                    account_id=graph_run.account_id,
                    character_id=graph_run.character_id,
                    entity_id=entity_id,
                    entity_kind=candidate.entity_kind,
                    canonical_name=candidate.canonical_name,
                    created_at_utc=now,
                    updated_at_utc=now,
                )
                await graph.upsert_entity(entity, connection=connection)
            if candidate.entity_id in resolved and resolved[candidate.entity_id] != entity_id:
                raise DomainInvariantError("memory entity key maps to multiple entities")
            resolved[candidate.entity_id] = entity_id
            await graph.add_alias(
                MemoryEntityAlias(
                    alias_id=uuid5(
                        NAMESPACE_URL,
                        f"memory-entity-alias:{graph_run.account_id}:{graph_run.character_id}:"
                        f"{normalized}",
                    ),
                    account_id=graph_run.account_id,
                    character_id=graph_run.character_id,
                    entity_id=entity_id,
                    alias_text=candidate.canonical_name,
                    normalized_alias=normalized,
                    created_at_utc=now,
                ),
                connection=connection,
            )
        return resolved

    async def _write_memory_entries(
        self,
        change_set: MemoryOrganizationChangeSet,
        *,
        graph_run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        entity_ids: dict[str, str],
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> dict[int, str]:
        memory_ids: dict[int, str] = {}
        for index, candidate in enumerate(change_set.memory_entries):
            fingerprint = content_fingerprint(
                {"graph_run_id": str(graph_run.graph_run_id), "candidate": candidate.model_dump()}
            ).value
            memory_id = f"reflection:{graph_run.graph_run_id}:{fingerprint}"
            entry = MemoryEntry(
                account_id=graph_run.account_id,
                character_id=graph_run.character_id,
                memory_id=memory_id,
                memory_kind=MemoryKind(candidate.memory_kind),
                content=candidate.content.strip(),
                source_kind="reflection",
                source_ref=memory_id,
                subject_kind=candidate.subject_kind,
                subject_id=entity_ids.get(candidate.subject_id, candidate.subject_id),
                visibility=MemoryVisibility(candidate.visibility),
                content_version=fingerprint,
                recorded_at_utc=now,
                confidence=candidate.confidence,
                salience=candidate.salience,
                occurred_at_utc=candidate.occurred_at_utc
                or _occurred_at(snapshot, candidate.source_refs, now),
                expires_at_utc=candidate.expires_at_utc,
            )
            await self.runtime.memory_entries.ensure(entry, connection=connection)
            memory_ids[index] = memory_id
            subject_entity_id = entity_ids.get(candidate.subject_id)
            if subject_entity_id is not None:
                await self.runtime.memory.memory_graph.link_entry_entity(
                    MemoryEntryEntityLink(
                        account_id=graph_run.account_id,
                        character_id=graph_run.character_id,
                        memory_id=memory_id,
                        entity_id=subject_entity_id,
                        role="subject",
                        created_at_utc=now,
                    ),
                    connection=connection,
                )
        return memory_ids

    async def _write_edges(
        self,
        change_set: MemoryOrganizationChangeSet,
        *,
        graph_run: ReflectionGraphRun,
        entity_ids: dict[str, str],
        memory_ids: dict[int, str],
        now: datetime,
        connection: aiosqlite.Connection,
    ) -> None:
        graph = self.runtime.memory.memory_graph
        for index, candidate in enumerate(change_set.edges):
            if (
                candidate.from_entity_id not in entity_ids
                or candidate.to_entity_id not in entity_ids
            ):
                raise DomainInvariantError("memory edge references an unknown entity key")
            source_memory_id = candidate.source_memory_id
            if source_memory_id is None:
                related = [
                    memory_ids[memory_index]
                    for memory_index, memory_candidate in enumerate(change_set.memory_entries)
                    if set(candidate.source_refs) & set(memory_candidate.source_refs)
                ]
                source_memory_id = related[0] if len(related) == 1 else None
            elif source_memory_id not in memory_ids.values():
                raise DomainInvariantError("memory edge references an unknown memory")
            fingerprint = content_fingerprint(
                {"graph_run_id": str(graph_run.graph_run_id), "edge": candidate.model_dump()}
            ).value
            await graph.add_edge(
                MemoryEdge(
                    edge_id=uuid5(
                        NAMESPACE_URL,
                        f"memory-edge:{graph_run.graph_run_id}:{fingerprint}:{index}",
                    ),
                    account_id=graph_run.account_id,
                    character_id=graph_run.character_id,
                    from_entity_id=entity_ids[candidate.from_entity_id],
                    to_entity_id=entity_ids[candidate.to_entity_id],
                    edge_kind=candidate.edge_kind,
                    confidence=candidate.confidence,
                    created_at_utc=now,
                    source_memory_id=source_memory_id,
                ),
                connection=connection,
            )


def _segment_source(graph_run: ReflectionGraphRun, segment: MemorySegment):
    for source in graph_run.source_scope.sources:
        if source.kind == "memory_segment" and source.ref == str(segment.segment_id):
            if source.version != segment.source_version:
                raise DomainInvariantError("reflection_segment_source_version_stale")
            return source
    raise DomainInvariantError("reflection_segment_source_missing")


async def _provenance_sources(
    segment: MemorySegment,
    snapshot: GraphContextSnapshot,
    connection: aiosqlite.Connection,
) -> tuple[MemorySourceRef, ...]:
    sources = await MemoryProvenanceRepository().segment_sources(
        str(segment.segment_id), connection=connection
    )
    if any(
        f"{source.kind.value}:{source.source_id}" not in snapshot.source_refs for source in sources
    ):
        raise DomainInvariantError("summary_source_coverage_incomplete")
    return sources


def _occurred_at(snapshot: GraphContextSnapshot, source_refs: Sequence[str], now: datetime):
    for material in snapshot.materials:
        if material.source_ref in source_refs and material.occurred_at_utc is not None:
            return material.occurred_at_utc
    return now


def _normalize_alias(value: str) -> str:
    return " ".join(value.casefold().split())


def _relationship_policy() -> RelationshipPolicy:
    return RelationshipPolicy(
        acquaintance_baseline=RelationshipValues(affection=50.0, trust=50.0, attachment=0.0),
        friend_minimum_affection=60.0,
        friend_minimum_trust=60.0,
        initializes_on=frozenset({RelationshipEvidenceKind.INTERACTION}),
        friend_qualifying_kinds=frozenset(
            {RelationshipEvidenceKind.SUPPORT, RelationshipEvidenceKind.COMMITMENT}
        ),
        attachment_qualifying_kinds=frozenset(
            {RelationshipEvidenceKind.SUPPORT, RelationshipEvidenceKind.COMMITMENT}
        ),
    )


__all__ = [
    "FactHandlerRegistry",
    "ReflectionGraphCommitService",
    "MemoryOrganizationCommitService",
    "ReflectionFactHandler",
    "RelationshipFactHandler",
    "SegmentSummaryHandler",
    "StateFactHandler",
]
