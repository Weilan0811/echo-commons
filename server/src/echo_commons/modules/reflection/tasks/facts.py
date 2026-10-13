import json
import sqlite3
from datetime import datetime

from echo_commons.modules.characters.contracts import CharacterFactWriter
from echo_commons.modules.characters.domain.changes import RelationshipChange, StateChange
from echo_commons.modules.characters.domain.relationship import (
    RelationshipDimension,
    RelationshipDirection,
    RelationshipEvidenceKind,
)
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.memory.contracts import (
    MemoryContinuityWriter,
    MemoryOrganizationWriter,
    MemorySegmentWriter,
    MemoryViewWriter,
)
from echo_commons.modules.memory.domain.organization import (
    MemoryEntryDraft,
    OrganizationEvidence,
)
from echo_commons.modules.memory.domain.views import MemoryViewDraft, ViewBranchResult
from echo_commons.modules.reflection.contracts.candidates import (
    ContinuityDigestCandidate,
    CoreMemoryRewriteCandidate,
    MemoryUpsertCandidate,
    ReflectionBatchOutcome,
    ReflectionBatchProposal,
    RelationshipImpactCandidate,
    SegmentSummaryCandidate,
    StateEntryCandidate,
    ViewRewriteCandidate,
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
        views: MemoryViewWriter,
    ) -> None:
        self.memory, self.characters = memory, characters
        self.continuity, self.organization = continuity, organization
        self.views = views

    def apply(
        self,
        connection: sqlite3.Connection,
        snapshot: GraphContextSnapshot,
        batch: ReflectionBatchProposal,
        now: datetime,
        *,
        supplement: bool = False,
        view_results: tuple[ViewBranchResult, ...] = (),
    ) -> None:
        if snapshot.graph_kind is ReflectionGraphKind.VIEW_REFRESH:
            views = []
            for candidate in batch.candidates:
                if (
                    isinstance(candidate, ViewRewriteCandidate)
                    and candidate.view_kind == "relationship_attitude"
                ):
                    if candidate.target is None:
                        raise ReflectionReviewError("reflection_view_target_unknown")
                    identity = (
                        f"{snapshot.scope.character_id}/{candidate.target.kind.value}/"
                        f"{candidate.target.actor_id}"
                    )
                    fact = next(item for item in snapshot.materials if item.source_id == identity)
                    content = json.loads(fact.content)
                    evidence_ids = (
                        tuple(item["evidence_id"] for item in content["evidence"])
                        if "evidence" in content
                        else None
                    )
                    self.characters.refresh_attitude(
                        connection,
                        snapshot.scope.community_id,
                        snapshot.scope.character_id,
                        candidate.target,
                        candidate.content,
                        snapshot.prepared_at_utc,
                        now,
                        evidence_ids=evidence_ids,
                    )
                else:
                    kind = (
                        "core_memory"
                        if isinstance(candidate, CoreMemoryRewriteCandidate)
                        else candidate.view_kind
                    )
                    views.append(MemoryViewDraft(kind, candidate.content, candidate.source_refs))
            self.views.apply(
                connection,
                snapshot.scope.community_id,
                snapshot.scope.character_id,
                snapshot.source_id,
                snapshot.source_version,
                tuple(views),
                bool(batch.candidates),
                now,
                view_results=view_results,
            )
            return
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
                    item.visibility,
                    item.confidence,
                    item.salience,
                    tuple(
                        OrganizationEvidence(material.kind, material.source_id, material.version)
                        for material in snapshot.materials
                        if material.evidence_ref in item.source_refs
                    ),
                )
                for item in batch.candidates
                if isinstance(item, MemoryUpsertCandidate)
            )
            self.organization.organize(
                connection,
                snapshot.scope.community_id,
                snapshot.scope.character_id,
                snapshot.source_id,
                entries,
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
                        RelationshipEvidenceKind(candidate.evidence_kind),
                    )
                )
            elif isinstance(candidate, StateEntryCandidate):
                states.append(StateChange(StateKind(candidate.state_kind), candidate.value))
        if summary is None and not supplement:
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
        if supplement:
            return
        self.memory.ingest(
            connection,
            snapshot.scope.community_id,
            snapshot.scope.character_id,
            snapshot.source_id,
            summary,
            now,
        )
