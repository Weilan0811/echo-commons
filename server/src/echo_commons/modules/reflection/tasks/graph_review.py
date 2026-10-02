from dataclasses import dataclass

from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.modules.reflection.contracts.candidates import (
    ContinuityDigestCandidate,
    ReflectionBatchOutcome,
    ReflectionBatchProposal,
    RelationshipImpactCandidate,
    SegmentSummaryCandidate,
    StateEntryCandidate,
)
from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot, MessageMaterial
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind

_KINDS = {
    ReflectionGraphKind.SEGMENT_REFLECT: {"segment_summary", "relationship_impact", "state_entry"},
    ReflectionGraphKind.CONTINUITY_COMPRESS: {"continuity_digest"},
    ReflectionGraphKind.MEMORY_ORGANIZE: {"memory_upsert", "memory_entity", "memory_edge"},
}


@dataclass(frozen=True, slots=True)
class GraphReview:
    max_candidates: int
    max_output_chars: int

    def check(self, snapshot: GraphContextSnapshot, batch: ReflectionBatchProposal) -> str | None:
        if snapshot.graph_kind not in _KINDS:
            return "reflection_graph_unimplemented"
        if (
            len(batch.candidates) > self.max_candidates
            or len(batch.model_dump_json()) > self.max_output_chars
        ):
            return "reflection_batch_too_large"
        if batch.outcome is ReflectionBatchOutcome.NO_OP:
            return None
        sources = {material.evidence_ref for material in snapshot.materials}
        messages = tuple(
            material for material in snapshot.materials if isinstance(material, MessageMaterial)
        )
        targets = source_actors(snapshot)
        relations, states = set(), set()
        for candidate in batch.candidates:
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
        if snapshot.graph_kind is ReflectionGraphKind.SEGMENT_REFLECT:
            summaries = tuple(
                item for item in batch.candidates if isinstance(item, SegmentSummaryCandidate)
            )
            if len(summaries) != 1:
                return "reflection_summary_required"
            if (summaries[0].first_message_sequence, summaries[0].last_message_sequence) != (
                min(material.message.sequence for material in messages),
                max(material.message.sequence for material in messages),
            ):
                return "reflection_summary_range_mismatch"
        elif snapshot.graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
            digests = tuple(
                item for item in batch.candidates if isinstance(item, ContinuityDigestCandidate)
            )
            upper = max(
                material.last_sequence
                for material in snapshot.materials
                if material.kind == "segment_summary"
            )
            if len(digests) != 1 or digests[0].covers_through_sequence != upper:
                return "reflection_digest_coverage_mismatch"
        return None
