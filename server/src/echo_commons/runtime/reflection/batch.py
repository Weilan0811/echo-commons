from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import BaseModel

from echo_commons.agents.contracts import (
    ProposalEnvelope,
    ProposalKind,
    ReflectionBatchProposal,
    ReflectionCandidate,
    ReflectionGraphOrigin,
)
from echo_commons.agents.contracts.reflection_graph import GraphContextSnapshot
from echo_commons.domain.errors import DomainInvariantError
from echo_commons.domain.reflection_graph import (
    ArtifactRef,
    ContentFingerprint,
    EvidenceRef,
    ReflectionArtifact,
    ReflectionGraphRun,
    content_fingerprint,
)
from echo_commons.domain.reflection_node import ReflectionNodeTask
from echo_commons.domain.reflection_rules import ReflectionOutcome, validate_reflection_outcome
from echo_commons.runtime.reflection.normalizer import ReflectionArtifactNormalizer


@dataclass(frozen=True, slots=True)
class NormalizedCandidate:
    """One candidate with the Artifact and typed evidence that produced it."""

    candidate: ReflectionCandidate
    artifact_ref: ArtifactRef
    evidence_refs: tuple[EvidenceRef, ...]
    candidate_fingerprint: ContentFingerprint | str = ""

    def __post_init__(self) -> None:
        if not isinstance(self.candidate, BaseModel):
            raise DomainInvariantError("normalized candidate must be a contract model")
        if not isinstance(self.artifact_ref, ArtifactRef):
            raise DomainInvariantError("normalized candidate must reference an Artifact")
        evidence = tuple(self.evidence_refs)
        if not evidence:
            raise DomainInvariantError("normalized candidate requires typed evidence")
        if any(not isinstance(ref, EvidenceRef) for ref in evidence):
            raise DomainInvariantError("normalized candidate evidence must be typed")
        if len({ref.identity for ref in evidence}) != len(evidence):
            raise DomainInvariantError("normalized candidate evidence must be unique")
        if not set(self.candidate.source_refs) <= {ref.ref for ref in evidence}:
            raise DomainInvariantError("candidate source refs must be backed by evidence")
        expected = content_fingerprint(self.candidate.model_dump(mode="json"))
        supplied = self.candidate_fingerprint
        if not supplied:
            supplied = expected
        elif not isinstance(supplied, ContentFingerprint):
            supplied = ContentFingerprint(supplied)
        if supplied != expected:
            raise DomainInvariantError("candidate fingerprint does not match candidate content")
        object.__setattr__(self, "evidence_refs", evidence)
        object.__setattr__(self, "candidate_fingerprint", supplied)


@dataclass(frozen=True, slots=True)
class ReflectionBatch:
    """The graph-level output sent to the single reflection Reviewer."""

    graph_run_id: UUID
    normalized_candidates: tuple[NormalizedCandidate, ...]
    artifact_refs: tuple[ArtifactRef, ...]
    outcome: ReflectionOutcome | str
    no_op_reason: str | None
    aggregate_fingerprint: ContentFingerprint | str

    def __post_init__(self) -> None:
        if not isinstance(self.graph_run_id, UUID):
            raise DomainInvariantError("graph_run_id must be a UUID")
        candidates = tuple(self.normalized_candidates)
        if any(not isinstance(item, NormalizedCandidate) for item in candidates):
            raise DomainInvariantError("ReflectionBatch contains an invalid candidate")
        artifacts = tuple(self.artifact_refs)
        if any(not isinstance(item, ArtifactRef) for item in artifacts):
            raise DomainInvariantError("ReflectionBatch contains an invalid ArtifactRef")
        if len({item.artifact_id for item in artifacts}) != len(artifacts):
            raise DomainInvariantError("ReflectionBatch Artifacts must be unique")
        if not {item.artifact_ref.artifact_id for item in candidates} <= {
            item.artifact_id for item in artifacts
        }:
            raise DomainInvariantError("candidate Artifacts must be included in artifact_refs")
        outcome = ReflectionOutcome(self.outcome)
        validate_reflection_outcome(
            outcome,
            produced_items=candidates,
            no_op_reason=self.no_op_reason,
        )
        fingerprint = (
            self.aggregate_fingerprint
            if isinstance(self.aggregate_fingerprint, ContentFingerprint)
            else ContentFingerprint(self.aggregate_fingerprint)
        )
        object.__setattr__(self, "normalized_candidates", candidates)
        object.__setattr__(self, "artifact_refs", artifacts)
        object.__setattr__(self, "outcome", outcome)
        object.__setattr__(self, "aggregate_fingerprint", fingerprint)

    @property
    def candidates(self) -> tuple[ReflectionCandidate, ...]:
        return tuple(item.candidate for item in self.normalized_candidates)

    @property
    def candidate_refs(self) -> tuple[ContentFingerprint, ...]:
        return tuple(item.candidate_fingerprint for item in self.normalized_candidates)

    def to_proposal_envelope(self) -> ProposalEnvelope:
        """Create the internal graph review Proposal without copied context."""

        return ProposalEnvelope(
            proposal_id=uuid5(
                NAMESPACE_URL,
                f"reflection-graph-proposal:{self.graph_run_id}:{self.aggregate_fingerprint}",
            ),
            kind=ProposalKind.REFLECTION_BATCH,
            origin=ReflectionGraphOrigin(graph_run_id=self.graph_run_id),
            payload=ReflectionBatchProposal(
                outcome=self.outcome.value,
                candidates=self.candidates,
                no_op_reason=self.no_op_reason,
            ),
        )

    def to_payload(self) -> dict[str, object]:
        """Return the bounded result body stored for inspection and replay."""

        return {
            "graph_run_id": str(self.graph_run_id),
            "artifact_refs": [
                {
                    "artifact_id": str(ref.artifact_id),
                    "content_fingerprint": ref.content_fingerprint.value,
                }
                for ref in self.artifact_refs
            ],
            "outcome": self.outcome.value,
            "no_op_reason": self.no_op_reason,
            "aggregate_fingerprint": self.aggregate_fingerprint.value,
            "candidates": [candidate.model_dump(mode="json") for candidate in self.candidates],
        }

    @classmethod
    def from_artifacts(
        cls,
        *,
        graph_run: ReflectionGraphRun,
        node_tasks: Sequence[ReflectionNodeTask],
        artifacts: Sequence[ReflectionArtifact],
        snapshot: GraphContextSnapshot,
        normalizer: ReflectionArtifactNormalizer | None = None,
    ) -> ReflectionBatch:
        """Normalize all non-aggregate node Artifacts in stable order."""

        if snapshot.snapshot_id != graph_run.context_snapshot_id:
            raise DomainInvariantError("graph run and snapshot IDs do not match")
        if snapshot.snapshot_fingerprint != graph_run.snapshot_fingerprint.value:
            raise DomainInvariantError("graph run and snapshot fingerprint do not match")

        task_by_id: dict[UUID, ReflectionNodeTask] = {}
        for task in node_tasks:
            if not isinstance(task, ReflectionNodeTask):
                raise DomainInvariantError("ReflectionBatch node_tasks must be NodeTask values")
            if task.graph_run_id != graph_run.graph_run_id:
                raise DomainInvariantError("NodeTask belongs to a different GraphRun")
            if task.task_id in task_by_id:
                raise DomainInvariantError("ReflectionBatch NodeTasks must be unique")
            task_by_id[task.task_id] = task

        normalizer = normalizer or ReflectionArtifactNormalizer()
        artifact_refs: list[ArtifactRef] = []
        seen_artifacts: set[UUID] = set()
        normalized: list[NormalizedCandidate] = []
        no_op_reasons: list[str] = []
        ordered = sorted(artifacts, key=lambda item: (str(item.node_task_id), item.attempt))
        for artifact in ordered:
            if not isinstance(artifact, ReflectionArtifact):
                raise DomainInvariantError("ReflectionBatch artifacts must be Artifact values")
            if artifact.artifact_id in seen_artifacts:
                raise DomainInvariantError("ReflectionBatch Artifacts must be unique")
            seen_artifacts.add(artifact.artifact_id)
            artifact_refs.append(artifact.reference)
            task = task_by_id.get(artifact.node_task_id)
            if task is None:
                continue
            if artifact.node_input_fingerprint != task.node_input_fingerprint:
                raise DomainInvariantError("Artifact node input fingerprint is stale")
            if artifact.output_contract != task.output_contract:
                raise DomainInvariantError("Artifact output contract differs from NodeTask")
            result = normalizer.normalize(
                artifact,
                snapshot,
                node_kind=task.node_kind,
                predecessor_artifact_refs=task.input_artifact_refs,
            )
            if result.outcome is ReflectionOutcome.NO_OP:
                if result.no_op_reason:
                    no_op_reasons.append(result.no_op_reason)
                continue
            normalized.extend(
                NormalizedCandidate(
                    candidate=candidate,
                    artifact_ref=result.artifact_ref,
                    evidence_refs=result.evidence_refs,
                )
                for candidate in result.candidates
            )

        normalized.sort(
            key=lambda item: (
                item.candidate_fingerprint.value,
                item.artifact_ref.content_fingerprint.value,
            )
        )
        outcome = ReflectionOutcome.PRODUCED if normalized else ReflectionOutcome.NO_OP
        no_op_reason = None
        if outcome is ReflectionOutcome.NO_OP:
            reasons = tuple(dict.fromkeys(reason for reason in no_op_reasons if reason))
            no_op_reason = "; ".join(reasons) or "reflection nodes produced no candidates"
        validate_reflection_outcome(
            outcome,
            produced_items=normalized,
            no_op_reason=no_op_reason,
        )
        aggregate_fingerprint = content_fingerprint(
            {
                "graph_run_id": str(graph_run.graph_run_id),
                "artifact_refs": [
                    {
                        "artifact_id": str(ref.artifact_id),
                        "content_fingerprint": ref.content_fingerprint.value,
                    }
                    for ref in artifact_refs
                ],
                "outcome": outcome.value,
                "no_op_reason": no_op_reason,
                "candidates": [
                    {
                        "candidate": item.candidate.model_dump(mode="json"),
                        "artifact_id": str(item.artifact_ref.artifact_id),
                        "evidence_refs": [
                            {"kind": ref.kind, "ref": ref.ref, "version": ref.version}
                            for ref in item.evidence_refs
                        ],
                    }
                    for item in normalized
                ],
            }
        )
        return cls(
            graph_run_id=graph_run.graph_run_id,
            normalized_candidates=tuple(normalized),
            artifact_refs=tuple(artifact_refs),
            outcome=outcome,
            no_op_reason=no_op_reason,
            aggregate_fingerprint=aggregate_fingerprint,
        )


__all__ = ["NormalizedCandidate", "ReflectionBatch"]
