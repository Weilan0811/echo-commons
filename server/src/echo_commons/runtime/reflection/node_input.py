from __future__ import annotations

from collections.abc import Mapping, Sequence

from echo_commons.agents.contracts import (
    ArtifactInput,
    ContextInputRef,
    GraphContextSnapshot,
    NodeInput,
    NodeInputProjection,
)
from echo_commons.agents.contracts import (
    EvidenceRef as ContractEvidenceRef,
)
from echo_commons.agents.contracts import (
    OutputContractRef as ContractOutputContractRef,
)
from echo_commons.domain.errors import DomainInvariantError, require_non_empty
from echo_commons.domain.reflection_graph import (
    EvidenceRef,
    ReflectionArtifact,
    ReflectionNodeDefinition,
    content_fingerprint,
)

_PROJECTION_FIELDS: Mapping[str, frozenset[str]] = {
    "segment_summary_plan": frozenset(
        {"identity", "character_state", "relationship_state", "memory_context", "materials"}
    ),
    "relationship_reflect": frozenset({"identity", "relationship_state", "materials"}),
    "state_reflect": frozenset({"identity", "character_state", "materials"}),
    "continuity_compress": frozenset({"identity", "memory_context", "materials"}),
    "page_compose": frozenset({"identity", "memory_context", "materials"}),
    "graph_extract": frozenset({"identity", "memory_context", "materials"}),
    "diary_compose": frozenset(
        {"identity", "character_state", "relationship_state", "memory_context", "materials"}
    ),
    "view_refresh_planner": frozenset(
        {"identity", "character_state", "relationship_state", "memory_context"}
    ),
    "relationship_attitude_view": frozenset({"identity", "relationship_state", "memory_context"}),
    "state_summary_view": frozenset({"identity", "character_state", "memory_context"}),
    "core_memory_view": frozenset({"identity", "memory_context"}),
    "segment_aggregate": frozenset(),
    "continuity_aggregate": frozenset(),
    "memory_aggregate": frozenset(),
    "diary_aggregate": frozenset(),
    "view_aggregate": frozenset(),
}


def _value(value: object) -> str:
    return value.value if hasattr(value, "value") else str(value)


class NodeInputProjector:
    """Project only the fields declared by a fixed Reflection node."""

    def project(
        self,
        snapshot: GraphContextSnapshot,
        node: ReflectionNodeDefinition,
        *,
        predecessor_artifacts: Sequence[ReflectionArtifact] = (),
        evidence_refs: Sequence[EvidenceRef] | None = None,
        model_profile: str = "strong",
        projection_fields: frozenset[str] | None = None,
    ) -> NodeInput:
        if not isinstance(snapshot, GraphContextSnapshot):
            raise DomainInvariantError("node input projection requires a GraphContextSnapshot")
        if not isinstance(node, ReflectionNodeDefinition):
            raise DomainInvariantError("node input projection requires a node definition")
        profile = require_non_empty(model_profile, "model profile")
        node_kind = _value(node.node_kind)
        fields = projection_fields or _PROJECTION_FIELDS.get(node_kind)
        if fields is None:
            raise DomainInvariantError(
                f"no projection policy is registered for node kind: {node_kind}"
            )
        unknown_fields = set(fields) - {
            "identity",
            "character_state",
            "relationship_state",
            "memory_context",
            "materials",
            "capability_view",
        }
        if unknown_fields:
            raise DomainInvariantError("node input projection contains unknown fields")

        projection = NodeInputProjection(
            identity=snapshot.identity if "identity" in fields else None,
            character_state=snapshot.character_state if "character_state" in fields else None,
            relationship_state=(
                snapshot.relationship_state if "relationship_state" in fields else None
            ),
            memory_context=snapshot.memory_context if "memory_context" in fields else None,
            window=snapshot.window,
            materials=snapshot.materials if "materials" in fields else (),
            capability_view=(snapshot.capability_view if "capability_view" in fields else None),
        )
        inputs = tuple(self._artifact_input(artifact) for artifact in predecessor_artifacts)
        normalized_evidence = self._evidence_refs(
            snapshot,
            projection,
            evidence_refs,
            predecessor_artifacts,
        )
        snapshot_ref = ContextInputRef(
            snapshot_id=snapshot.snapshot_id,
            snapshot_schema_version=snapshot.snapshot_schema_version,
            snapshot_fingerprint=snapshot.snapshot_fingerprint,
        )
        output_contract = ContractOutputContractRef(
            kind=node.output_contract.kind,
            version=node.output_contract.version,
        )
        fingerprint_payload = {
            "input_schema_version": 1,
            "snapshot_ref": snapshot_ref.model_dump(mode="json"),
            "node_key": node.node_key,
            "node_kind": node_kind,
            "input_contract": node.input_contract,
            "output_contract": output_contract.schema_id,
            "model_profile": profile,
            "projection": projection.model_dump(mode="json"),
            "predecessor_artifacts": [
                {
                    "artifact_id": str(item.artifact_id),
                    "content_fingerprint": item.reference.content_fingerprint.value,
                }
                for item in inputs
            ],
            "evidence_refs": [item.model_dump(mode="json") for item in normalized_evidence],
        }
        input_fingerprint = content_fingerprint(fingerprint_payload).value
        return NodeInput(
            snapshot_ref=snapshot_ref,
            node_key=node.node_key,
            node_kind=node_kind,
            input_contract=node.input_contract,
            output_contract=output_contract,
            model_profile=profile,
            projection=projection,
            predecessor_artifacts=inputs,
            evidence_refs=normalized_evidence,
            node_input_fingerprint=input_fingerprint,
        )

    @staticmethod
    def _artifact_input(artifact: ReflectionArtifact) -> ArtifactInput:
        if not isinstance(artifact, ReflectionArtifact):
            raise DomainInvariantError("predecessor inputs must be ReflectionArtifact values")
        return ArtifactInput(
            reference=artifact.reference,
            output_contract=ContractOutputContractRef(
                kind=artifact.output_contract.kind,
                version=artifact.output_contract.version,
            ),
            payload=artifact.payload,
            evidence_refs=tuple(
                ContractEvidenceRef(kind=ref.kind, ref=ref.ref, version=ref.version)
                for ref in artifact.evidence_refs
            ),
        )

    @staticmethod
    def _evidence_refs(
        snapshot: GraphContextSnapshot,
        projection: NodeInputProjection,
        evidence_refs: Sequence[EvidenceRef] | None,
        predecessor_artifacts: Sequence[ReflectionArtifact],
    ) -> tuple[ContractEvidenceRef, ...]:
        allowed_sources = set(snapshot.source_refs)
        allowed_artifacts = {
            f"artifact:{artifact.artifact_id}" for artifact in predecessor_artifacts
        }
        selected = tuple(evidence_refs or ())
        if not selected:
            source_versions = {item.ref: item.version for item in snapshot.source_scope.sources}
            selected = tuple(
                EvidenceRef(
                    kind="source",
                    ref=material.source_ref,
                    version=source_versions.get(material.source_ref)
                    or material.content_version
                    or None,
                )
                for material in projection.materials
                if material.source_ref in allowed_sources
            )
        normalized: list[ContractEvidenceRef] = []
        seen: set[tuple[str, str]] = set()
        for ref in selected:
            if not isinstance(ref, EvidenceRef):
                raise DomainInvariantError("node input evidence refs must be EvidenceRef values")
            if ref.identity in seen:
                raise DomainInvariantError("node input evidence refs must be unique")
            seen.add(ref.identity)
            if ref.kind == "source" and ref.ref not in allowed_sources:
                raise DomainInvariantError("node input evidence is outside the graph snapshot")
            if ref.kind == "artifact" and ref.ref not in allowed_artifacts:
                raise DomainInvariantError("node input Artifact evidence is not a predecessor")
            normalized.append(ContractEvidenceRef(kind=ref.kind, ref=ref.ref, version=ref.version))
        return tuple(normalized)


__all__ = ["NodeInputProjector"]
