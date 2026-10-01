from __future__ import annotations

from collections.abc import Sequence
from dataclasses import dataclass
from typing import TypeAlias

from pydantic import BaseModel, TypeAdapter, ValidationError

from echo_commons.agents.contracts import (
    ContinuityDigestAction,
    ContinuityDigestCandidate,
    CoreMemoryRewriteCandidate,
    DiaryAction,
    DiaryAppendCandidate,
    GraphExtractionAction,
    LongTermMemoryPageAction,
    MemoryEdgeCandidate,
    MemoryEntityCandidate,
    MemoryUpsertCandidate,
    NoOpReflectionAction,
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
from echo_commons.agents.contracts.reflection_graph import GraphContextSnapshot
from echo_commons.domain.errors import DomainInvariantError
from echo_commons.domain.reflection_graph import (
    ArtifactRef,
    EvidenceRef,
    FrozenPayload,
    ReflectionArtifact,
    ReflectionNodeKind,
)
from echo_commons.domain.reflection_rules import (
    ReflectionOutcome,
    validate_reflection_outcome,
)

_ACTION_ADAPTER = TypeAdapter(ReflectionNodeAction)
_NODE_ACTION_KINDS: dict[str, frozenset[str]] = {
    "segment_summary_plan": frozenset({"segment_summary"}),
    "relationship_reflect": frozenset({"relationship_reflection"}),
    "state_reflect": frozenset({"state_reflection"}),
    "continuity_compress": frozenset({"continuity_digest"}),
    "page_compose": frozenset({"long_term_memory_page"}),
    "graph_extract": frozenset({"graph_extraction"}),
    "diary_compose": frozenset({"diary"}),
    "view_refresh_planner": frozenset({"view_refresh"}),
    "relationship_attitude_view": frozenset({"view_refresh"}),
    "state_summary_view": frozenset({"view_refresh"}),
    "core_memory_view": frozenset({"view_refresh"}),
}

Action: TypeAlias = ReflectionNodeAction


@dataclass(frozen=True, slots=True)
class ArtifactNormalization:
    """The stable result of normalizing one successful node Artifact."""

    artifact_ref: ArtifactRef
    candidates: tuple[ReflectionCandidate, ...]
    evidence_refs: tuple[EvidenceRef, ...]
    outcome: ReflectionOutcome
    no_op_reason: str | None = None

    def __post_init__(self) -> None:
        if not isinstance(self.artifact_ref, ArtifactRef):
            raise DomainInvariantError("normalized Artifact must have an ArtifactRef")
        if any(not isinstance(candidate, BaseModel) for candidate in self.candidates):
            raise DomainInvariantError("normalized candidates must contain candidate values")
        object.__setattr__(self, "outcome", ReflectionOutcome(self.outcome))
        validate_reflection_outcome(
            self.outcome,
            produced_items=self.candidates,
            no_op_reason=self.no_op_reason,
        )


class ReflectionArtifactNormalizer:
    """Turn one ``reflection_node.v1`` Artifact into zero, one, or many candidates.

    The Artifact's persisted evidence is authoritative.  Action-level evidence,
    when present, may only narrow that set; it cannot introduce a new source.
    """

    def normalize(
        self,
        artifact: ReflectionArtifact,
        snapshot: GraphContextSnapshot,
        *,
        node_kind: ReflectionNodeKind | str | None = None,
        predecessor_artifact_refs: Sequence[ArtifactRef] = (),
    ) -> ArtifactNormalization:
        if not isinstance(artifact, ReflectionArtifact):
            raise DomainInvariantError("Artifact normalization requires a ReflectionArtifact")
        if not isinstance(snapshot, GraphContextSnapshot):
            raise DomainInvariantError("Artifact normalization requires a GraphContextSnapshot")
        if artifact.output_contract.schema_id != "reflection_node.v1":
            raise DomainInvariantError("Artifact output contract must be reflection_node.v1")

        action = self._parse_action(artifact.payload)
        if node_kind is not None:
            self._validate_node_action_kind(node_kind, action)
        evidence_refs = self._validate_evidence(
            artifact.evidence_refs,
            action.evidence_refs,
            snapshot,
            predecessor_artifact_refs,
        )
        if isinstance(action, NoOpReflectionAction):
            return ArtifactNormalization(
                artifact_ref=artifact.reference,
                candidates=(),
                evidence_refs=evidence_refs,
                outcome=ReflectionOutcome.NO_OP,
                no_op_reason=action.reason.strip(),
            )

        candidates = self._candidates(action, evidence_refs, snapshot)
        validate_reflection_outcome(
            ReflectionOutcome.PRODUCED,
            produced_items=candidates,
        )
        return ArtifactNormalization(
            artifact_ref=artifact.reference,
            candidates=tuple(candidates),
            evidence_refs=evidence_refs,
            outcome=ReflectionOutcome.PRODUCED,
        )

    @staticmethod
    def _parse_action(payload: FrozenPayload) -> Action:
        try:
            return _ACTION_ADAPTER.validate_python(payload.to_dict())
        except ValidationError as exc:
            raise DomainInvariantError(
                "Artifact payload does not match the reflection node action contract"
            ) from exc

    @staticmethod
    def _validate_node_action_kind(
        node_kind: ReflectionNodeKind | str,
        action: Action,
    ) -> None:
        normalized_node_kind = (
            node_kind.value if isinstance(node_kind, ReflectionNodeKind) else str(node_kind)
        )
        if isinstance(action, NoOpReflectionAction):
            return
        allowed = _NODE_ACTION_KINDS.get(normalized_node_kind)
        if allowed is None:
            raise DomainInvariantError(
                f"node kind {normalized_node_kind} cannot produce a model Artifact"
            )
        if action.kind not in allowed:
            raise DomainInvariantError(
                f"action kind {action.kind} is not allowed for node kind {normalized_node_kind}"
            )

    @staticmethod
    def _validate_evidence(
        artifact_evidence: Sequence[EvidenceRef],
        action_evidence: Sequence[str],
        snapshot: GraphContextSnapshot,
        predecessor_artifact_refs: Sequence[ArtifactRef],
    ) -> tuple[EvidenceRef, ...]:
        persisted = tuple(artifact_evidence)
        if any(not isinstance(ref, EvidenceRef) for ref in persisted):
            raise DomainInvariantError("Artifact evidence must contain EvidenceRef values")
        selected_identities: set[tuple[str, str]] | None = None
        for selector in action_evidence:
            if not isinstance(selector, str) or not selector.strip():
                raise DomainInvariantError("action evidence selectors must contain text")
            matches = tuple(
                ref for ref in persisted if ref.kind != "artifact" and ref.ref == selector.strip()
            )
            if len(matches) != 1:
                raise DomainInvariantError("action evidence is not declared by the Artifact")
            if selected_identities is None:
                selected_identities = set()
            selected_identities.add(matches[0].identity)

        sources = {
            (source.kind, source.ref): source.version for source in snapshot.source_scope.sources
        }
        source_refs = {source.ref: source.version for source in snapshot.source_scope.sources}
        predecessor_by_ref = {
            f"artifact:{item.artifact_id}": item.content_fingerprint.value
            for item in predecessor_artifact_refs
        }
        normalized: list[EvidenceRef] = []
        for ref in persisted:
            if ref.kind == "artifact":
                expected = predecessor_by_ref.get(ref.ref)
                if expected is None:
                    raise DomainInvariantError("Artifact evidence is not a predecessor Artifact")
                if ref.version != expected:
                    raise DomainInvariantError("predecessor Artifact evidence version is stale")
            elif ref.kind == "source":
                expected = source_refs.get(ref.ref)
                if expected is None:
                    raise DomainInvariantError("source evidence is outside the graph snapshot")
                if ref.version != expected:
                    raise DomainInvariantError("source evidence version is stale")
            else:
                expected = sources.get(ref.identity)
                if expected is None:
                    raise DomainInvariantError(
                        "typed source evidence is outside the graph snapshot"
                    )
                if ref.version != expected:
                    raise DomainInvariantError("typed source evidence version is stale")
            if (
                selected_identities is None
                or ref.kind == "artifact"
                or ref.identity in selected_identities
            ):
                normalized.append(ref)
        return tuple(normalized)

    @staticmethod
    def _source_refs(evidence_refs: Sequence[EvidenceRef]) -> tuple[str, ...]:
        # Candidate.source_refs is the compatibility projection used by the
        # existing reviewer.  Typed predecessor Artifact evidence remains on
        # NormalizedCandidate.evidence_refs and is not mistaken for a source.
        refs = tuple(ref.ref for ref in evidence_refs if ref.kind != "artifact")
        if not refs:
            raise DomainInvariantError("produced reflection candidate requires evidence")
        if len(refs) != len(set(refs)):
            raise DomainInvariantError("candidate evidence references must be unique")
        return refs

    def _candidates(
        self,
        action: Action,
        evidence_refs: tuple[EvidenceRef, ...],
        snapshot: GraphContextSnapshot,
    ) -> list[ReflectionCandidate]:
        source_refs = self._source_refs(evidence_refs)
        if isinstance(action, SegmentSummaryAction):
            window = snapshot.window
            if window.first_message_sequence is None or window.last_message_sequence is None:
                raise DomainInvariantError(
                    "segment summary requires Runtime-owned message sequence bounds"
                )
            return [
                SegmentSummaryCandidate(
                    source_refs=source_refs,
                    summary=action.summary,
                    first_message_sequence=window.first_message_sequence,
                    last_message_sequence=window.last_message_sequence,
                )
            ]
        if isinstance(action, RelationshipReflectionAction):
            return [
                RelationshipImpactCandidate(
                    source_refs=source_refs,
                    dimension=item.dimension,
                    direction=item.direction,
                    level=item.level,
                )
                for item in action.dimensions
            ]
        if isinstance(action, StateReflectionAction):
            return [
                StateEntryCandidate(
                    source_refs=source_refs,
                    state_kind=action.state_kind,
                    value=action.value,
                )
            ]
        if isinstance(action, ContinuityDigestAction):
            return [
                ContinuityDigestCandidate(
                    source_refs=source_refs,
                    content=action.content,
                    covers_through_sequence=action.covers_through_sequence,
                    content_version=action.content_version,
                )
            ]
        if isinstance(action, LongTermMemoryPageAction):
            return [
                MemoryUpsertCandidate(
                    source_refs=source_refs,
                    memory_kind=item.memory_kind,
                    content=item.content,
                    subject_kind=item.subject_kind,
                    subject_id=item.subject_id,
                    confidence=item.confidence,
                    salience=item.salience,
                )
                for item in action.pages
            ]
        if isinstance(action, GraphExtractionAction):
            candidates: list[ReflectionCandidate] = [
                MemoryEntityCandidate(
                    source_refs=source_refs,
                    entity_id=item.entity_id,
                    entity_kind=item.entity_kind,
                    canonical_name=item.canonical_name,
                )
                for item in action.entities
            ]
            candidates.extend(
                MemoryEdgeCandidate(
                    source_refs=source_refs,
                    from_entity_id=item.from_entity_id,
                    to_entity_id=item.to_entity_id,
                    edge_kind=item.edge_kind,
                    confidence=item.confidence,
                )
                for item in action.edges
            )
            return candidates
        if isinstance(action, DiaryAction):
            return [
                DiaryAppendCandidate(
                    source_refs=source_refs,
                    game_day=action.game_day,
                    content=action.content,
                )
            ]
        if isinstance(action, ViewRefreshAction):
            if action.view_kind == "core_memory":
                supporting_memory_ids = tuple(
                    item.strip() for item in action.supporting_memory_ids if item.strip()
                )
                if not supporting_memory_ids:
                    raise DomainInvariantError(
                        "core memory view refresh requires supporting memory IDs"
                    )
                return [
                    CoreMemoryRewriteCandidate(
                        source_refs=source_refs,
                        content=action.content,
                        supporting_memory_ids=supporting_memory_ids,
                    )
                ]
            return [
                ViewRewriteCandidate(
                    source_refs=source_refs,
                    view_kind=action.view_kind,
                    content=action.content,
                )
            ]
        raise DomainInvariantError(f"unsupported reflection action: {type(action).__name__}")


__all__ = ["ArtifactNormalization", "ReflectionArtifactNormalizer"]
