from dataclasses import dataclass

from echo_commons.modules.reflection.budget import ReflectionBudget
from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.modules.reflection.contracts.candidates import (
    ContinuityDigestCandidate,
    CoreMemoryRewriteCandidate,
    ReflectionBatchOutcome,
    ReflectionBatchProposal,
    RelationshipImpactCandidate,
    SegmentSummaryCandidate,
    StateEntryCandidate,
    ViewRewriteCandidate,
)
from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind
from echo_commons.modules.reflection.tasks.review import relationship_description_required

_KINDS = {
    ReflectionGraphKind.SEGMENT_REFLECT: {"segment_summary", "relationship_impact", "state_entry"},
    ReflectionGraphKind.CONTINUITY_COMPRESS: {"continuity_digest"},
    ReflectionGraphKind.MEMORY_ORGANIZE: {"memory_fact", "memory_cognition"},
    ReflectionGraphKind.VIEW_REFRESH: {"core_memory_rewrite", "view_rewrite"},
}


@dataclass(frozen=True, slots=True)
class GraphReview:
    max_candidates: int
    max_output_chars: int
    budget: ReflectionBudget | None = None

    def check(
        self,
        snapshot: GraphContextSnapshot,
        batch: ReflectionBatchProposal,
        *,
        supplement: bool = False,
    ) -> str | None:
        if snapshot.graph_kind not in _KINDS:
            return "reflection_graph_unimplemented"
        count, chars = (
            self.budget or ReflectionBudget(self.max_candidates, self.max_output_chars)
        ).limits(snapshot)
        if len(batch.candidates) > count or batch.content_chars > chars:
            return "reflection_batch_too_large"
        if batch.outcome is ReflectionBatchOutcome.NO_OP:
            if not supplement and relationship_description_required(snapshot.materials):
                return "reflection_relationship_description_required"
            if snapshot.graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
                return "reflection_digest_required"
            return None
        sources = {
            material.evidence_ref for material in snapshot.materials if not material.context_only
        }
        targets = source_actors(snapshot)
        relations, states = set(), set()
        for candidate in batch.candidates:
            if isinstance(candidate, ViewRewriteCandidate) and (
                candidate.view_kind == "relationship_attitude"
            ):
                if (
                    len(candidate.content)
                    > (self.budget or ReflectionBudget()).relationship_attitude_max_chars
                ):
                    return "reflection_relationship_attitude_too_long"
                if candidate.target not in targets:
                    return "reflection_view_target_unknown"
            if (
                isinstance(candidate, CoreMemoryRewriteCandidate)
                and len(candidate.content)
                > (self.budget or ReflectionBudget()).core_memory_max_chars
            ):
                return "reflection_core_memory_too_long"
            if candidate.kind not in _KINDS[snapshot.graph_kind]:
                return "reflection_candidate_kind_mismatch"
            if not set(candidate.source_refs) <= sources:
                return "reflection_candidate_source_unknown"
            if isinstance(candidate, RelationshipImpactCandidate):
                identity = (candidate.target, candidate.dimension)
                if candidate.target not in targets:
                    return "reflection_relationship_target_unknown"
                if identity in relations:
                    return "reflection_relationship_duplicate"
                relations.add(identity)
            elif isinstance(candidate, StateEntryCandidate):
                if candidate.state_kind in states:
                    return "reflection_state_duplicate"
                states.add(candidate.state_kind)
        if snapshot.graph_kind is ReflectionGraphKind.SEGMENT_REFLECT and not supplement:
            summaries = tuple(
                item for item in batch.candidates if isinstance(item, SegmentSummaryCandidate)
            )
            if len(summaries) != 1:
                return "reflection_summary_required"
            originals = {
                material.evidence_ref
                for material in snapshot.materials
                if material.kind in ("message", "thought") and not material.context_only
            }
            if set(summaries[0].source_refs) != originals:
                return "reflection_summary_range_mismatch"
        elif snapshot.graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
            digests = tuple(
                item for item in batch.candidates if isinstance(item, ContinuityDigestCandidate)
            )
            if len(digests) != 1:
                return "reflection_digest_coverage_mismatch"
        return None
