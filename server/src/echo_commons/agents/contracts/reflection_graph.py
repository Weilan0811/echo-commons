"""Immutable graph snapshot and node-input contracts.

The Runtime owns construction of these values. Agents receive a projected
``NodeInput`` and never receive a Repository or a task scheduler object.
"""

from __future__ import annotations

import hashlib
import json
from typing import Literal
from uuid import UUID

from pydantic import (
    BaseModel,
    ConfigDict,
    Field,
    field_serializer,
    field_validator,
    model_validator,
)

from echo_server.agents.contracts.context import (
    CapabilityView,
    CharacterStateSnapshot,
    IdentityContext,
    MemoryContext,
    RelationshipStateSnapshot,
)
from echo_server.agents.contracts.reflection import EvidenceRef
from echo_server.agents.contracts.reflection_context import (
    ReflectionContext,
    ReflectionSourceMaterial,
    ReflectionWindowContext,
)
from echo_server.agents.contracts.refs import ContextInputRef, OutputContractRef
from echo_server.domain.reflection_graph import ArtifactRef, FrozenPayload

GRAPH_CONTEXT_SNAPSHOT_VERSION = 1
NODE_INPUT_VERSION = 1


def _named(value: str, field_name: str) -> str:
    normalized = value.strip()
    if not normalized:
        raise ValueError(f"{field_name} must contain text")
    return normalized


class GraphSourceReference(BaseModel):
    """One source identity visible to a graph run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: str = Field(min_length=1, max_length=100)
    ref: str = Field(min_length=1, max_length=300)
    version: str = Field(min_length=1, max_length=200)

    @field_validator("kind", "ref", "version")
    @classmethod
    def fields_must_contain_text(cls, value: str, info: object) -> str:
        return _named(value, getattr(info, "field_name", "value"))


class GraphSourceScope(BaseModel):
    """The source boundary shared by every node in one graph snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    sources: tuple[GraphSourceReference, ...] = Field(min_length=1, max_length=512)

    @model_validator(mode="after")
    def sources_must_be_unique(self) -> GraphSourceScope:
        identities = tuple((item.kind, item.ref) for item in self.sources)
        if len(identities) != len(set(identities)):
            raise ValueError("graph source scope sources must be unique")
        return self

    @property
    def source_refs(self) -> tuple[str, ...]:
        return tuple(item.ref for item in self.sources)


class GraphContextSnapshot(BaseModel):
    """One immutable, task-independent context for a graph run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_id: str = Field(min_length=1, max_length=200)
    snapshot_schema_version: Literal[1] = GRAPH_CONTEXT_SNAPSHOT_VERSION
    snapshot_fingerprint: str = Field(min_length=1, max_length=200)
    account_id: str = Field(min_length=1, max_length=200)
    character_id: str = Field(min_length=1, max_length=200)
    context: ReflectionContext
    capability_view: CapabilityView = Field(default_factory=CapabilityView)
    source_scope: GraphSourceScope

    @model_validator(mode="after")
    def snapshot_identity_and_fingerprint_must_match(self) -> GraphContextSnapshot:
        if self.context.character_id != self.character_id:
            raise ValueError("graph snapshot character_id does not match context")
        expected = graph_snapshot_fingerprint(
            account_id=self.account_id,
            character_id=self.character_id,
            context=self.context,
            capability_view=self.capability_view,
            source_scope=self.source_scope,
        )
        if self.snapshot_fingerprint != expected:
            raise ValueError("graph snapshot fingerprint does not match content")
        return self

    @classmethod
    def create(
        cls,
        *,
        snapshot_id: str,
        account_id: str,
        character_id: str,
        context: ReflectionContext,
        capability_view: CapabilityView,
        source_scope: GraphSourceScope,
    ) -> GraphContextSnapshot:
        fingerprint = graph_snapshot_fingerprint(
            account_id=account_id,
            character_id=character_id,
            context=context,
            capability_view=capability_view,
            source_scope=source_scope,
        )
        return cls(
            snapshot_id=snapshot_id,
            snapshot_fingerprint=fingerprint,
            account_id=account_id,
            character_id=character_id,
            context=context,
            capability_view=capability_view,
            source_scope=source_scope,
        )

    @property
    def source_refs(self) -> tuple[str, ...]:
        return self.source_scope.source_refs

    @property
    def has_window_material(self) -> bool:
        """Whether the source scope contains material from the active window."""

        return any(source.kind.startswith("conversation_") for source in self.source_scope.sources)

    @property
    def identity(self) -> IdentityContext:
        return self.context.identity

    @property
    def character_state(self) -> CharacterStateSnapshot:
        return self.context.character_state

    @property
    def relationship_state(self) -> RelationshipStateSnapshot:
        return self.context.relationship_state

    @property
    def memory_context(self) -> MemoryContext:
        return self.context.memory_context

    @property
    def window(self) -> ReflectionWindowContext:
        return self.context.window

    @property
    def materials(self) -> tuple[ReflectionSourceMaterial, ...]:
        return self.context.materials


class ArtifactInput(BaseModel):
    """Bounded predecessor Artifact projection supplied to one node."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    reference: ArtifactRef
    output_contract: OutputContractRef
    payload: FrozenPayload
    evidence_refs: tuple[EvidenceRef, ...] = Field(default=(), max_length=64)

    @field_serializer("payload")
    def serialize_payload(self, value: FrozenPayload) -> dict[str, object]:
        return value.to_dict()

    @property
    def artifact_id(self) -> UUID:
        return self.reference.artifact_id


class NodeInputProjection(BaseModel):
    """Optional typed fields selected by ``NodeInputProjector``."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: IdentityContext | None = None
    character_state: CharacterStateSnapshot | None = None
    relationship_state: RelationshipStateSnapshot | None = None
    memory_context: MemoryContext | None = None
    window: ReflectionWindowContext
    materials: tuple[ReflectionSourceMaterial, ...] = Field(default=(), max_length=256)
    capability_view: CapabilityView | None = None

    @model_validator(mode="after")
    def materials_must_be_unique(self) -> NodeInputProjection:
        refs = tuple(item.source_ref for item in self.materials)
        if len(refs) != len(set(refs)):
            raise ValueError("node input materials must not repeat source_ref")
        return self


class NodeInput(BaseModel):
    """The only context a Reflection node may receive from Runtime."""

    model_config = ConfigDict(extra="forbid", frozen=True, arbitrary_types_allowed=True)

    input_schema_version: Literal[1] = NODE_INPUT_VERSION
    snapshot_ref: ContextInputRef
    node_key: str = Field(min_length=1, max_length=200)
    node_kind: str = Field(min_length=1, max_length=100)
    input_contract: str = Field(min_length=1, max_length=100)
    output_contract: OutputContractRef
    model_profile: str = Field(min_length=1, max_length=100)
    projection: NodeInputProjection
    predecessor_artifacts: tuple[ArtifactInput, ...] = Field(default=(), max_length=64)
    evidence_refs: tuple[EvidenceRef, ...] = Field(default=(), max_length=128)
    node_input_fingerprint: str = Field(min_length=1, max_length=200)

    @model_validator(mode="after")
    def predecessor_refs_must_be_unique(self) -> NodeInput:
        ids = tuple(item.artifact_id for item in self.predecessor_artifacts)
        if len(ids) != len(set(ids)):
            raise ValueError("node input predecessor Artifacts must be unique")
        evidence = tuple((item.kind, item.ref) for item in self.evidence_refs)
        if len(evidence) != len(set(evidence)):
            raise ValueError("node input evidence refs must be unique")
        return self

    @property
    def character_id(self) -> str:
        for candidate in (self.projection.identity, self.projection.character_state):
            if candidate is not None:
                return candidate.character_id
        raise ValueError("node input projection does not identify a character")

    @property
    def source_refs(self) -> tuple[str, ...]:
        return tuple(item.source_ref for item in self.projection.materials)

    @property
    def window(self) -> ReflectionWindowContext:
        return self.projection.window

    @property
    def materials(self) -> tuple[ReflectionSourceMaterial, ...]:
        return self.projection.materials


def graph_snapshot_fingerprint(
    *,
    account_id: str,
    character_id: str,
    context: ReflectionContext,
    capability_view: CapabilityView,
    source_scope: GraphSourceScope,
) -> str:
    """Compute content identity without task, lease, or invocation metadata."""

    payload = {
        "schema_version": GRAPH_CONTEXT_SNAPSHOT_VERSION,
        "account_id": account_id,
        "character_id": character_id,
        "context": context.model_dump(
            mode="json",
            exclude={"now_utc"},
        ),
        "capability_view": capability_view.model_dump(mode="json"),
        "source_scope": {
            "sources": [
                item.model_dump(mode="json")
                for item in sorted(source_scope.sources, key=lambda item: (item.kind, item.ref))
            ],
        },
    }
    return hashlib.sha256(
        json.dumps(payload, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode(
            "utf-8"
        )
    ).hexdigest()


__all__ = [
    "ArtifactInput",
    "GRAPH_CONTEXT_SNAPSHOT_VERSION",
    "GraphContextSnapshot",
    "GraphSourceReference",
    "GraphSourceScope",
    "NODE_INPUT_VERSION",
    "NodeInput",
    "NodeInputProjection",
    "graph_snapshot_fingerprint",
]
