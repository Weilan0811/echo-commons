import sqlite3
from datetime import datetime

from echo_commons.modules.characters.contracts import CharacterFactWriter
from echo_commons.modules.characters.domain.changes import RelationshipChange, StateChange
from echo_commons.modules.characters.domain.relationship import (
    RelationshipDimension,
    RelationshipDirection,
)
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.memory.contracts import (
    MemoryContinuityWriter,
    MemoryOrganizationWriter,
    MemorySegmentWriter,
)
from echo_commons.modules.memory.domain.organization import (
    MemoryEdgeDraft,
    MemoryEntityDraft,
    MemoryEntryDraft,
)
from echo_commons.modules.reflection.contracts.candidates import (
    ContinuityDigestCandidate,
    MemoryEdgeCandidate,
    MemoryEntityCandidate,
    MemoryUpsertCandidate,
    ReflectionBatchOutcome,
    ReflectionBatchProposal,
    RelationshipImpactCandidate,
    SegmentSummaryCandidate,
    StateEntryCandidate,
)
from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot
from echo_commons.modules.reflection.domain.graph import (
    ReflectionGraphKind,
)
from echo_commons.modules.reflection.tasks.errors import ReflectionReviewError


class ReflectionFacts:
    def __init__(
        self,
        memory: MemorySegmentWriter,
        characters: CharacterFactWriter,
        continuity: MemoryContinuityWriter,
        organization: MemoryOrganizationWriter,
    ) -> None:
        self.memory, self.characters = memory, characters
        self.continuity, self.organization = continuity, organization

    def apply(
        self,
        connection: sqlite3.Connection,
        snapshot: GraphContextSnapshot,
        batch: ReflectionBatchProposal,
        now: datetime,
    ) -> None:
        if snapshot.graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
            digest = next(
                (item for item in batch.candidates if isinstance(item, ContinuityDigestCandidate)),
                None,
            )
            if digest is None:
                raise ReflectionReviewError("reflection_digest_required")
            self.continuity.compress(
                connection,
                snapshot.scope.community_id,
                snapshot.scope.character_id,
                snapshot.source_id,
                digest.content,
                snapshot.observation_upper_sequence,
                now,
            )
            return
        if snapshot.graph_kind is ReflectionGraphKind.MEMORY_ORGANIZE:
            entries = tuple(
                MemoryEntryDraft(
                    item.memory_kind,
                    item.content,
                    item.subject_kind,
                    item.subject_id,
                    item.visibility,
                    item.confidence,
                    item.salience,
                )
                for item in batch.candidates
                if isinstance(item, MemoryUpsertCandidate)
            )
            entities = tuple(
                MemoryEntityDraft(item.entity_id, item.entity_kind, item.canonical_name)
                for item in batch.candidates
                if isinstance(item, MemoryEntityCandidate)
            )
            edges = tuple(
                MemoryEdgeDraft(
                    item.from_entity_id, item.to_entity_id, item.edge_kind, item.confidence
                )
                for item in batch.candidates
                if isinstance(item, MemoryEdgeCandidate)
            )
            self.organization.organize(
                connection,
                snapshot.scope.community_id,
                snapshot.scope.character_id,
                snapshot.source_id,
                entries,
                entities,
                edges,
                batch.outcome is ReflectionBatchOutcome.NO_OP,
                now,
            )
            return
        if snapshot.graph_kind is not ReflectionGraphKind.SEGMENT_REFLECT:
            raise ValueError("Graph kind has no connected fact writer")
        relations, states = [], []
        summary = None
        materials = {material.evidence_ref: material for material in snapshot.materials}
        for candidate in batch.candidates:
            if isinstance(candidate, SegmentSummaryCandidate):
                summary = candidate.summary
            elif isinstance(candidate, RelationshipImpactCandidate):
                occurred = max(
                    materials[ref].message.occurred_at_utc
                    if materials[ref].kind == "message"
                    else materials[ref].occurred_at_utc
                    for ref in candidate.source_refs
                )
                relations.append(
                    RelationshipChange(
                        candidate.target,
                        RelationshipDimension(candidate.dimension),
                        {
                            "positive": RelationshipDirection.UP,
                            "negative": RelationshipDirection.DOWN,
                            "neutral": RelationshipDirection.NEUTRAL,
                        }[candidate.direction],
                        candidate.level,
                        occurred,
                    )
                )
            elif isinstance(candidate, StateEntryCandidate):
                states.append(StateChange(StateKind(candidate.state_kind), candidate.value))
        if summary is None:
            raise ReflectionReviewError("reflection_summary_required")
        self.characters.apply(
            connection,
            snapshot.scope.community_id,
            snapshot.scope.character_id,
            snapshot.source_kind,
            snapshot.source_id,
            tuple(relations),
            tuple(states),
            now,
        )
        self.memory.ingest(
            connection,
            snapshot.scope.community_id,
            snapshot.scope.character_id,
            snapshot.source_id,
            summary,
            now,
        )
