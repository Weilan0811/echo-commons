from pydantic import TypeAdapter

from echo_commons.modules.reflection.contracts.candidates import (
    ContinuityDigestAction,
    ContinuityDigestCandidate,
    CoreMemoryRewriteCandidate,
    MemoryCognitionCandidate,
    MemoryCognitionReflectAction,
    MemoryFactCandidate,
    MemoryFactExtractAction,
    MemoryFactReviewAction,
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
from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot
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
        if isinstance(action, MemoryFactExtractAction):
            continue
        if isinstance(action, MemoryFactReviewAction):
            candidates.extend(
                MemoryFactCandidate(source_refs=item.evidence_refs, operation=item)
                for item in action.facts
            )
            if not action.facts:
                reasons.append("本批原文没有需要保存的新事实。")
            continue
        if isinstance(action, MemoryCognitionReflectAction):
            candidates.extend(
                MemoryCognitionCandidate(source_refs=item.evidence_refs, operation=item)
                for item in action.cognitions
            )
            continue
        refs = source_refs(artifact)
        if not refs:
            raise ReflectionReviewError("reflection_evidence_missing")
        if isinstance(action, SegmentSummaryAction):
            candidates.append(
                SegmentSummaryCandidate(
                    source_refs=refs,
                    summary=action.summary,
                )
            )
        elif isinstance(action, RelationshipReflectionAction):
            candidates.extend(
                RelationshipImpactCandidate(
                    source_refs=item.evidence_refs,
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
                )
            )
        elif isinstance(action, ViewRefreshAction):
            if action.view_kind == "core_memory":
                candidates.append(
                    CoreMemoryRewriteCandidate(
                        source_refs=refs,
                        content=action.content,
                        supporting_records=action.supporting_records,
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
