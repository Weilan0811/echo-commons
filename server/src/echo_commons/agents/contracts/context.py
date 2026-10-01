from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.shared.actors import ActorRef

CONTEXT_SNAPSHOT_VERSION = 1
PROMPT_LAYOUT_VERSION = 1


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SnapshotScope(SnapshotModel):
    community_id: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    conversation_id: str = Field(min_length=1)
    membership_id: str = Field(min_length=1)
    observation_upper_sequence: int = Field(ge=0)
    social_turn_id: str | None = None


class ObservedMessage(SnapshotModel):
    message_id: str
    sequence: int = Field(ge=1)
    sender: ActorRef
    sender_name: str
    text: str
    occurred_at_utc: datetime
    reply_to_message_id: str | None = None


class RelationshipView(SnapshotModel):
    target: ActorRef
    target_name: str
    relationship_type: str
    attitude: str = ""


class SelfContext(SnapshotModel):
    character_id: str
    name: str
    blueprint_id: str
    blueprint_version: str
    agent_contract: str
    profile: str
    voice: str
    relational_dynamics: str
    mood: str = ""
    physical_state: str = ""
    activity: str = ""
    intent: str = ""
    relationships: tuple[RelationshipView, ...] = ()
    capabilities: tuple[str, ...] = ()


class PerspectiveContext(SnapshotModel):
    inputs: tuple[ObservedMessage, ...] = ()
    history: tuple[ObservedMessage, ...] = ()
    public_facts: tuple[str, ...] = ()


class MemoryItem(SnapshotModel):
    memory_id: str
    content_version: str
    content: str


class MemoryContext(SnapshotModel):
    resident: tuple[MemoryItem, ...] = ()
    recalled: tuple[MemoryItem, ...] = ()
    session_digest: str = ""


class EnvironmentContext(SnapshotModel):
    world_time_utc: datetime
    community_status: str
    conversation_kind: str


class ActionSpace(SnapshotModel):
    output_contracts: tuple[OutputContractRef, ...]
    tools: tuple[str, ...] = ()


class SourceVersion(SnapshotModel):
    kind: str
    source_id: str
    version: str


class ContextSnapshot(SnapshotModel):
    schema_version: Literal[1] = CONTEXT_SNAPSHOT_VERSION
    prompt_layout_version: Literal[1] = PROMPT_LAYOUT_VERSION
    snapshot_id: str = Field(min_length=1)
    prepared_at_utc: datetime
    scope: SnapshotScope
    self: SelfContext
    perspective: PerspectiveContext
    memory: MemoryContext
    environment: EnvironmentContext
    action_space: ActionSpace
    source_versions: tuple[SourceVersion, ...]
