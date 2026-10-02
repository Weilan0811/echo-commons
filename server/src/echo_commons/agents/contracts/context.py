from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_commons.agents.contracts.input import ActorScope, InvocationInput, ToolReadPolicy
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.message_sources import MessageSource

CONTEXT_SNAPSHOT_VERSION = 1
PROMPT_LAYOUT_VERSION = 1


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SnapshotScope(ActorScope):
    conversation_id: str = Field(min_length=1)
    membership_id: str = Field(min_length=1)
    observation_upper_sequence: int = Field(ge=0)
    social_turn_id: str | None = None


class ObservedMessage(SnapshotModel):
    message_id: str
    sequence: int = Field(ge=1)
    sender: MessageSource
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
    availability: Literal["available", "busy", "offline"] = "available"
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


class HistoricalThought(SnapshotModel):
    message_id: str
    thought_id: str
    content_version: str
    content: str


class ConversationSummary(SnapshotModel):
    segment_id: str
    content_version: str
    content: str
    first_sequence: int = Field(ge=1)
    last_sequence: int = Field(ge=1)


class MemoryContext(SnapshotModel):
    resident: tuple[MemoryItem, ...] = ()
    recalled: tuple[MemoryItem, ...] = ()
    session_digest: str = ""
    history_thoughts: tuple[HistoricalThought, ...] = ()
    segment_summaries: tuple[ConversationSummary, ...] = ()


class EnvironmentContext(SnapshotModel):
    world_time_utc: datetime
    community_status: str
    conversation_kind: str


class ContextSnapshot(InvocationInput):
    prompt_layout_version: Literal[1] = PROMPT_LAYOUT_VERSION
    scope: SnapshotScope
    self: SelfContext
    perspective: PerspectiveContext
    memory: MemoryContext
    environment: EnvironmentContext

    @model_validator(mode="after")
    def own_identity(self):
        if self.self.character_id != self.scope.character_id:
            raise ValueError("snapshot self identity does not match scope")
        own_messages = {
            message.message_id
            for message in self.perspective.history
            if message.sender == ActorRef("character", self.scope.character_id)
        }
        if any(thought.message_id not in own_messages for thought in self.memory.history_thoughts):
            raise ValueError("Historical Thought requires the character's own visible message")
        return self

    @property
    def read_policy(self) -> ToolReadPolicy:
        return ToolReadPolicy(
            observed_at_utc=self.prepared_at_utc,
            conversation_id=self.scope.conversation_id,
            upper_sequence=self.scope.observation_upper_sequence,
            source_versions=self.source_versions,
        )
