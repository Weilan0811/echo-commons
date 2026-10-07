from pydantic import TypeAdapter

from echo_commons.modules.reflection.contracts.candidates import (
    ContinuityDigestAction,
    ContinuityDigestCandidate,
    CoreMemoryRewriteCandidate,
    GraphExtractionAction,
    LongTermMemoryPageAction,
    MemoryEdgeCandidate,
    MemoryEntityCandidate,
    MemoryUpsertCandidate,
    NoOpReflectionAction,
    ReflectionBatchOutcome,
    ReflectionBatchProposal,
    ReflectionCandidate,
    ReflectionNodeAction,
    RelationshipImpactCandidate,
    RelationshipReflectionAction,
    SegmentSummaryAction,
    SegmentSummaryCandidate,
    StateEntryCandidate,
    StateReflectionAction,
    ViewRefreshAction,
    ViewRewriteCandidate,
)
from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot, MessageMaterial
from echo_commons.modules.reflection.domain.graph import ReflectionArtifact
from echo_commons.modules.reflection.tasks.errors import ReflectionReviewError

_ACTION = TypeAdapter(ReflectionNodeAction)


def aggregate_artifacts(
    snapshot: GraphContextSnapshot,
    artifacts: tuple[ReflectionArtifact, ...],
    *,
    max_candidates: int,
) -> ReflectionBatchProposal:
    by_id = {str(artifact.artifact_id): artifact for artifact in artifacts}
    sources = {material.evidence_ref: material.version for material in snapshot.materials}

    def source_refs(artifact: ReflectionArtifact) -> tuple[str, ...]:
        refs = []
        for evidence in artifact.evidence_refs:
            if evidence.kind == "artifact":
                predecessor = by_id.get(evidence.ref)
                if predecessor is None or str(predecessor.content_fingerprint) != evidence.version:
                    raise ReflectionReviewError("reflection_artifact_mismatch")
                refs.extend(source_refs(predecessor))
            else:
                identity = f"{evidence.kind}:{evidence.ref}"
                if sources.get(identity) != evidence.version:
                    raise ReflectionReviewError("reflection_evidence_mismatch")
                refs.append(identity)
        return tuple(dict.fromkeys(refs))

    candidates: list[ReflectionCandidate] = []
    reasons = []
    for artifact in artifacts:
        action = _ACTION.validate_python(artifact.payload.to_dict())
        if isinstance(action, NoOpReflectionAction):
            reasons.append(action.reason)
            continue
        refs = source_refs(artifact)
        if not refs:
            raise ReflectionReviewError("reflection_evidence_missing")
        if isinstance(action, SegmentSummaryAction):
            messages = tuple(
                material.message
                for material in snapshot.materials
                if isinstance(material, MessageMaterial)
            )
            candidates.append(
                SegmentSummaryCandidate(
                    source_refs=refs,
                    summary=action.summary,
                    first_message_sequence=min(message.sequence for message in messages),
                    last_message_sequence=max(message.sequence for message in messages),
                )
            )
        elif isinstance(action, RelationshipReflectionAction):
            candidates.extend(
                RelationshipImpactCandidate(
                    source_refs=refs,
                    target=item.target,
                    dimension=item.dimension,
                    direction=item.direction,
                    level=item.level,
                    evidence_kind=item.evidence_kind,
                )
                for item in action.dimensions
            )
        elif isinstance(action, StateReflectionAction):
            candidates.append(
                StateEntryCandidate(
                    source_refs=refs,
                    state_kind=action.state_kind,
                    value=action.value,
                )
            )
        elif isinstance(action, ContinuityDigestAction):
            candidates.append(
                ContinuityDigestCandidate(
                    source_refs=refs,
                    content=action.content,
                    covers_through_sequence=action.covers_through_sequence,
                    content_version=action.content_version,
                )
            )
        elif isinstance(action, LongTermMemoryPageAction):
            candidates.extend(
                MemoryUpsertCandidate(
                    source_refs=refs,
                    memory_kind=item.memory_kind,
                    content=item.content,
                    subject_kind=item.subject_kind,
                    subject_id=item.subject_id,
                    confidence=item.confidence,
                    salience=item.salience,
                )
                for item in action.pages
            )
        elif isinstance(action, GraphExtractionAction):
            candidates.extend(
                MemoryEntityCandidate(
                    source_refs=refs,
                    entity_id=item.entity_id,
                    entity_kind=item.entity_kind,
                    canonical_name=item.canonical_name,
                )
                for item in action.entities
            )
            candidates.extend(
                MemoryEdgeCandidate(
                    source_refs=refs,
                    from_entity_id=item.from_entity_id,
                    to_entity_id=item.to_entity_id,
                    edge_kind=item.edge_kind,
                    confidence=item.confidence,
                )
                for item in action.edges
            )
        elif isinstance(action, ViewRefreshAction):
            if action.view_kind == "core_memory":
                candidates.append(
                    CoreMemoryRewriteCandidate(
                        source_refs=refs,
                        content=action.content,
                        supporting_memory_ids=action.supporting_memory_ids,
                    )
                )
            else:
                candidates.append(
                    ViewRewriteCandidate(
                        source_refs=refs,
                        view_kind=action.view_kind,
                        content=action.content,
                        target=action.target,
                    )
                )
        else:
            raise ReflectionReviewError("reflection_action_unimplemented")
    if len(candidates) > max_candidates:
        raise ReflectionReviewError("reflection_candidate_limit_exceeded")
    if candidates:
        return ReflectionBatchProposal(candidates=tuple(candidates))
    if not reasons:
        raise ReflectionReviewError("reflection_batch_empty")
    return ReflectionBatchProposal(
        outcome=ReflectionBatchOutcome.NO_OP,
        no_op_reason="；".join(dict.fromkeys(reasons))[:500],
    )
