from datetime import datetime
from typing import Literal

from pydantic import BaseModel, ConfigDict, Field, model_serializer, model_validator

from echo_commons.agents.contracts.input import ActorScope, InvocationInput, ToolReadPolicy
from echo_commons.infrastructure.models.budget import InputBudget
from echo_commons.modules.perspective.contracts import ConversationBoundary
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.message_sources import MessageSource

CONTEXT_SNAPSHOT_VERSION = 2
PROMPT_LAYOUT_VERSION = 3


class SnapshotModel(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class SnapshotScope(ActorScope):
    conversation_id: str = Field(min_length=1)
    membership_id: str = Field(min_length=1)
    observation_upper_sequence: int = Field(ge=0)
    social_turn_id: str | None = None
    initiation_id: str | None = None
    conversations: tuple[ConversationBoundary, ...] = ()

    @model_serializer(mode="wrap")
    def serialize_scope(self, handler):
        result = handler(self)
        if "initiation_id" not in self.model_fields_set:
            result.pop("initiation_id", None)
        return result


class ObservedMessage(SnapshotModel):
    message_id: str
    conversation_id: str
    sequence: int = Field(ge=1)
    sender: MessageSource
    sender_name: str
    text: str
    occurred_at_utc: datetime
    reply_to_message_id: str | None = None
    mentions: tuple[ActorRef, ...] = ()
    mention_names: tuple[str, ...] = ()
    visibility: str = "群内可见"

    @model_serializer(mode="wrap")
    def serialize_frozen(self, handler):
        result = handler(self)
        for name in ("mentions", "mention_names"):
            if name not in self.model_fields_set:
                result.pop(name, None)
        return result


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


class ParticipantIdentity(SnapshotModel):
    actor: ActorRef
    display_name: str
    is_self: bool


class PerspectiveContext(SnapshotModel):
    participants: tuple[ParticipantIdentity, ...] = ()
    inputs: tuple[ObservedMessage, ...] = ()
    history: tuple[ObservedMessage, ...] = ()
    public_facts: tuple[str, ...] = ()
    situation: str = ""
    trigger_message_ids: tuple[str, ...] = ()

    @model_serializer(mode="wrap")
    def serialize_frozen(self, handler):
        result = handler(self)
        for name in ("trigger_message_ids", "situation", "participants"):
            if name not in self.model_fields_set:
                result.pop(name, None)
        return result


class MemoryItem(SnapshotModel):
    memory_id: str
    content_version: str
    content: str
    source_kind: str = "memory"
    occurred_at_utc: datetime | None = None
    context_label: str = ""

    @model_serializer(mode="wrap")
    def serialize_frozen(self, handler):
        result = handler(self)
        for name in ("source_kind", "occurred_at_utc", "context_label"):
            if name not in self.model_fields_set:
                result.pop(name, None)
        return result


class HistoricalThought(SnapshotModel):
    message_id: str
    thought_id: str
    content_version: str
    content: str


class ConversationSummary(SnapshotModel):
    segment_id: str
    content_version: str
    content: str
    started_at_utc: datetime
    ended_at_utc: datetime
    conversations: tuple[ConversationBoundary, ...]


class MemoryContext(SnapshotModel):
    protected_message_ids: tuple[str, ...] = ()
    input_budget: InputBudget | None = None
    current_ratio: float = Field(default=0.6, gt=0, lt=1)
    nearby_ratio: float = Field(default=0.3, ge=0, lt=1)
    context_prepared: bool = True
    covered_message_ids: tuple[str, ...] = ()
    summary_message_ids: tuple[str, ...] = ()
    retrieval_prepared: bool = True
    retrieval_query: str = ""
    resident: tuple[MemoryItem, ...] = ()
    recalled: tuple[MemoryItem, ...] = ()
    session_digest: str = ""
    core_memory: str = ""
    state_summary: str = ""
    history_thoughts: tuple[HistoricalThought, ...] = ()
    segment_summaries: tuple[ConversationSummary, ...] = ()

    @model_serializer(mode="wrap")
    def serialize_frozen(self, handler):
        result = handler(self)
        # 冻结输入不能因新增可选字段而改变原有序列化内容。
        for name in (
            "protected_message_ids",
            "retrieval_prepared",
            "retrieval_query",
            "core_memory",
            "state_summary",
            "input_budget",
            "current_ratio",
            "nearby_ratio",
            "context_prepared",
            "covered_message_ids",
            "summary_message_ids",
        ):
            if name not in self.model_fields_set:
                result.pop(name, None)
        return result


class EnvironmentContext(SnapshotModel):
    world_time_utc: datetime
    community_status: str
    conversation_kind: str
    timezone: str = "UTC"
    world_description: str = ""
    community_rules: str = ""
    community_version: int = 0

    @model_serializer(mode="wrap")
    def serialize_frozen(self, handler):
        result = handler(self)
        for name in ("timezone", "world_description", "community_rules", "community_version"):
            if name not in self.model_fields_set:
                result.pop(name, None)
        return result


class ContextSnapshot(InvocationInput):
    schema_version: Literal[2] = CONTEXT_SNAPSHOT_VERSION
    prompt_layout_version: Literal[2, 3] = PROMPT_LAYOUT_VERSION
    scope: SnapshotScope
    self: SelfContext
    perspective: PerspectiveContext
    memory: MemoryContext
    environment: EnvironmentContext

    @property
    def current_messages(self) -> tuple[ObservedMessage, ...]:
        return tuple(
            sorted(
                (
                    message
                    for message in (*self.perspective.history, *self.perspective.inputs)
                    if message.conversation_id == self.scope.conversation_id
                ),
                key=lambda message: message.sequence,
            )
        )

    def reply_target(self, number: int) -> ObservedMessage:
        messages = self.current_messages
        if number < 1 or number > len(messages):
            raise ValueError("reply_to must refer to a numbered current-conversation message")
        return messages[number - 1]

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
            conversations=self.scope.conversations,
        )
