from datetime import datetime
from typing import Annotated, Literal, TypeAlias

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_commons.agents.contracts.context import (
    EnvironmentContext,
    MemoryContext,
    ObservedMessage,
    SelfContext,
)
from echo_commons.agents.contracts.input import (
    ActionSpace,
    ActorScope,
    InvocationInput,
    SourceVersion,
    ToolReadPolicy,
)
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.modules.reflection.contracts.candidates import ReflectionNodeAction
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind, ReflectionNodeKind
from echo_commons.shared.actors import ActorRef

REFLECTION_NODE_CONTRACT = OutputContractRef(kind="reflection_node", version="v1")
MEMORY_NODE_CONTRACT = OutputContractRef(kind="reflection_node", version="v5")
VIEW_NODE_CONTRACT = OutputContractRef(kind="reflection_node", version="v3")


class ReflectionModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class MaterialSource(ReflectionModel):
    source_id: str = Field(min_length=1)
    version: str = Field(min_length=1)
    kind: str

    @property
    def evidence_ref(self) -> str:
        return f"{self.kind}:{self.source_id}"


class MessageMaterial(MaterialSource):
    kind: Literal["message"] = "message"
    message: ObservedMessage
    mentions: tuple[ActorRef, ...] = ()

    @model_validator(mode="after")
    def source_identity(self):
        if self.source_id != self.message.message_id:
            raise ValueError("Message material identity disagrees with its source")
        return self


class ThoughtMaterial(MaterialSource):
    kind: Literal["thought"] = "thought"
    content: str = Field(min_length=1)
    occurred_at_utc: datetime


class SummaryMaterial(MaterialSource):
    kind: Literal["segment_summary"] = "segment_summary"
    content: str = Field(min_length=1)
    first_sequence: int = Field(ge=1)
    last_sequence: int = Field(ge=1)


class DigestMaterial(MaterialSource):
    kind: Literal["conversation_digest"] = "conversation_digest"
    content: str = Field(min_length=1)
    covers_through_sequence: int = Field(ge=1)


class AuthorMaterialSource(MaterialSource):
    kind: Literal["author_chunk"] = "author_chunk"
    content: str = Field(min_length=1)
    known_at_utc: datetime | None = None


class FactMaterial(MaterialSource):
    kind: Literal["formal_fact"] = "formal_fact"
    content: str = Field(min_length=1)
    fact_kind: Literal[
        "memory_fact", "memory_cognition", "character_state", "relationship", "core_memory_request"
    ]


NonThoughtMaterial: TypeAlias = (
    MessageMaterial | SummaryMaterial | DigestMaterial | AuthorMaterialSource | FactMaterial
)

ReflectionMaterial: TypeAlias = Annotated[
    NonThoughtMaterial | ThoughtMaterial,
    Field(discriminator="kind"),
]


class GraphContextSnapshot(ReflectionModel):
    schema_version: Literal[1] = 1
    snapshot_id: str = Field(min_length=1)
    prepared_at_utc: datetime
    scope: ActorScope
    graph_kind: ReflectionGraphKind
    source_kind: Literal[
        "memory_segment", "memory_summary_batch", "author_material_batch", "memory_change_set"
    ]
    source_id: str = Field(min_length=1)
    source_version: str = Field(min_length=1)
    conversation_id: str | None = Field(default=None, min_length=1)
    observation_upper_sequence: int = Field(ge=0)
    self: SelfContext
    memory: MemoryContext
    environment: EnvironmentContext
    public_facts: tuple[str, ...] = ()
    materials: tuple[ReflectionMaterial, ...] = Field(min_length=1)
    action_space: ActionSpace
    source_versions: tuple[SourceVersion, ...]

    @model_validator(mode="after")
    def own_identity(self):
        if self.self.character_id != self.scope.character_id:
            raise ValueError("Reflection identity disagrees with its character scope")
        identities = [(source.kind, source.source_id) for source in self.materials]
        if len(identities) != len(set(identities)):
            raise ValueError("Reflection materials contain duplicate sources")
        return self


class ArtifactInput(ReflectionModel):
    artifact_id: str
    node_key: str
    content_version: str
    payload: ReflectionNodeAction


class ReflectionNodeInput(InvocationInput):
    graph_run_id: str = Field(min_length=1)
    node_key: str = Field(min_length=1)
    node_kind: ReflectionNodeKind
    graph_snapshot: GraphContextSnapshot
    artifacts: tuple[ArtifactInput, ...] = ()

    @model_validator(mode="after")
    def graph_scope(self):
        if self.scope != self.graph_snapshot.scope:
            raise ValueError("Reflection node scope disagrees with its graph snapshot")
        if self.prepared_at_utc != self.graph_snapshot.prepared_at_utc:
            raise ValueError("Reflection node observation time disagrees with its graph snapshot")
        if self.action_space != self.graph_snapshot.action_space:
            raise ValueError("Reflection node action space disagrees with its graph snapshot")
        return self

    @property
    def read_policy(self) -> ToolReadPolicy:
        return ToolReadPolicy(
            observed_at_utc=self.prepared_at_utc,
            conversation_id=self.graph_snapshot.conversation_id,
            upper_sequence=(
                self.graph_snapshot.observation_upper_sequence
                if self.graph_snapshot.conversation_id
                else None
            ),
            source_versions=self.source_versions,
        )
