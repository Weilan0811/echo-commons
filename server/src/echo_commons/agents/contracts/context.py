"""Versioned, provider-neutral context contracts for Agent Runs.

The Runtime owns the snapshot boundary.  The nested models deliberately keep
stable identity, resident memory, conversation continuity, and volatile state
separate so a later source can replace one part without reshaping the whole
invocation contract.
"""

from __future__ import annotations

from datetime import datetime
from typing import Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

CONTEXT_SNAPSHOT_VERSION = 2
PROMPT_LAYOUT_VERSION = 8


class AgentMessage(BaseModel):
    """A message projected into an Agent context snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    message_id: UUID
    message_sequence: int = 0
    sender_type: str
    sender_id: str
    text: str
    thought: str | None = None
    images: tuple[str, ...] = ()
    server_timestamp_utc: datetime
    reply_to_message_id: UUID | None = None


class ContextRequest(BaseModel):
    """The immutable request-local part of a V2 snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str
    character_id: str
    trigger_message: AgentMessage
    input_messages: tuple[AgentMessage, ...] = ()


class IdentityContext(BaseModel):
    """Static character resources and their independently versioned pieces."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    contract_resource_id: str = Field(min_length=1)
    contract_content: str = Field(min_length=1)
    contract_version: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    bundle_version: str = Field(min_length=1)
    profile_resource_id: str = Field(min_length=1)
    profile_content: str = Field(min_length=1)
    profile_version: str = Field(min_length=1)
    voice_resource_id: str | None = None
    voice_content: str = ""
    voice_version: str | None = None
    relational_dynamics_resource_id: str | None = None
    relational_dynamics_content: str = ""
    relational_dynamics_version: str | None = None

    @property
    def composed_content(self) -> str:
        """Return the character identity prose as one prompt-ready block."""

        parts = [self.profile_content]
        if self.relational_dynamics_content:
            parts.append(self.relational_dynamics_content)
        if self.voice_content:
            parts.append(self.voice_content)
        return "\n\n".join(parts)


class CharacterStateSnapshot(BaseModel):
    """Current character condition and the separate reply-availability state."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    character_id: str
    availability_version: int = Field(default=0, ge=0)
    availability_status: str = "available"
    availability_reason: str | None = None
    next_check_at_utc: datetime | None = None
    physical_condition: str = ""
    mood: str = ""
    current_activity: str = ""
    availability_updated_at_utc: datetime | None = None


class RelationshipStateSnapshot(BaseModel):
    """Directed relationship state, including private scores for Runtime use."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    subject_id: str
    state_version: int = Field(default=0, ge=0)
    relationship_type: Literal["stranger", "acquaintance", "friend"] = "stranger"
    affection: float | None = Field(default=None, ge=0.0, le=100.0)
    trust: float | None = Field(default=None, ge=0.0, le=100.0)
    attachment: float | None = Field(default=None, ge=0.0, le=100.0)
    attitude_summary: str = ""
    updated_at_utc: datetime | None = None


class MemoryItem(BaseModel):
    """A bounded memory projection, not the authoritative memory record."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    memory_id: str
    content_version: str = ""
    summary: str
    memory_kind: Literal["fact", "event", "preference", "promise", "thread", "other"] = "other"
    confidence: float = Field(default=1.0, ge=0.0, le=1.0)
    salience: float = Field(default=0.5, ge=0.0, le=1.0)
    source: str = ""
    occurred_at_utc: datetime | None = None
    updated_at_utc: datetime | None = None


class MemoryAccessPolicy(BaseModel):
    """The read boundary for external memory during this Agent Run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    search_enabled: bool = False
    search_tool_name: str = "memory_search"
    max_results: int = Field(default=5, ge=1, le=50)
    guidance: str = ""
    expected_source_version: str | None = None
    retrieval_policy_version: str = "sparse-v2"
    frozen_conversation_id: str | None = None
    frozen_max_sequence: int | None = None


class MemoryContext(BaseModel):
    """Resident memory plus explicitly recalled memory for one invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    core_memory: MemoryItem | None = None
    state_summary: MemoryItem | None = None
    resident: tuple[MemoryItem, ...] = ()
    recalled: tuple[MemoryItem, ...] = ()
    access_policy: MemoryAccessPolicy = Field(default_factory=MemoryAccessPolicy)
    resident_version: str = "empty"
    recalled_query: str | None = None


class SessionDigest(BaseModel):
    """A resumable summary of recent conversation continuity."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    digest_id: str
    content: str
    covers_through_sequence: int = Field(ge=0)
    content_version: str
    created_at_utc: datetime | None = None


class SegmentSummary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    segment_id: str
    content: str
    content_version: str
    first_message_sequence: int
    last_message_sequence: int


class ActiveThread(BaseModel):
    """A currently open conversational thread, not a durable memory itself."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    thread_id: str
    summary: str
    status: Literal["open", "waiting", "resolved", "unknown"] = "open"
    updated_at_utc: datetime | None = None


class ConversationContinuity(BaseModel):
    """The semi-stable bridge between a session digest and the raw tail."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    session_digest: SessionDigest | None = None
    segment_summaries: tuple[SegmentSummary, ...] = ()
    active_threads: tuple[ActiveThread, ...] = ()
    recent_tail: tuple[AgentMessage, ...] = ()
    raw_tail_limit: int = Field(default=20, ge=0)


class SituationView(BaseModel):
    """Current situational observations, without pretending to be omniscience."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    world_phase: str = ""
    stage_summary: str = ""
    ambient_summary: str = ""
    observed_events: tuple[str, ...] = ()
    uncertainty_note: str = ""
    world_time_utc: datetime | None = None


class CapabilityDefinition(BaseModel):
    """A static action definition that can be advertised to an Agent."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    name: str
    description: str
    parameters: dict[str, object] = Field(default_factory=dict)
    action_kind: Literal["read", "proposal", "external"] = "read"


class CapabilityView(BaseModel):
    """Static capability catalog attached to one immutable snapshot."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    available: tuple[CapabilityDefinition, ...] = ()


class SnapshotSourceVersion(BaseModel):
    """Safe provenance metadata; it never contains prompt or player text."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    source: str
    version: str


class ContextSnapshotV2(BaseModel):
    """The canonical nested context assembled for one Agent invocation."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    snapshot_version: Literal[2] = CONTEXT_SNAPSHOT_VERSION
    conversation_id: str
    character_id: str
    context_version: str
    now_utc: datetime
    request: ContextRequest
    identity: IdentityContext
    character_state: CharacterStateSnapshot
    relationship_state: RelationshipStateSnapshot
    memory_context: MemoryContext = Field(default_factory=MemoryContext)
    conversation_continuity: ConversationContinuity = Field(default_factory=ConversationContinuity)
    situation: SituationView = Field(default_factory=SituationView)
    capability_view: CapabilityView = Field(default_factory=CapabilityView)
    source_versions: tuple[SnapshotSourceVersion, ...] = ()
    prompt_layout_version: int = Field(default=PROMPT_LAYOUT_VERSION, ge=1)

    @property
    def input_fingerprint(self) -> str:
        from echo_server.domain.memory_sources import content_version

        payload = self.model_dump(mode="json", exclude={"now_utc", "context_version"})
        return content_version(payload)

    @property
    def trigger_message(self) -> AgentMessage:
        return self.request.trigger_message

    @property
    def input_messages(self) -> tuple[AgentMessage, ...]:
        return self.request.input_messages

    @property
    def recent_messages(self) -> tuple[AgentMessage, ...]:
        return self.conversation_continuity.recent_tail

    @property
    def baseline_resource_id(self) -> str:
        return self.identity.contract_resource_id

    @property
    def baseline_content(self) -> str:
        return self.identity.contract_content

    @property
    def baseline_version(self) -> str:
        return self.identity.contract_version

    @property
    def identity_resource_id(self) -> str:
        return self.identity.character_id

    @property
    def identity_content(self) -> str:
        return self.identity.composed_content

    @property
    def identity_version(self) -> str:
        return self.identity.bundle_version

    @property
    def stage_summary(self) -> str:
        return self.situation.stage_summary


class ContextSourceSnapshot(BaseModel):
    """Repository-backed state and memory output consumed by the V2 builder."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    character_state: CharacterStateSnapshot
    relationship_state: RelationshipStateSnapshot
    memory_context: MemoryContext = Field(default_factory=MemoryContext)
    session_digest: SessionDigest | None = None
    segment_summaries: tuple[SegmentSummary, ...] = ()
    active_threads: tuple[ActiveThread, ...] = ()
    situation: SituationView = Field(default_factory=SituationView)
    source_versions: tuple[SnapshotSourceVersion, ...] = ()


__all__ = [
    "CONTEXT_SNAPSHOT_VERSION",
    "PROMPT_LAYOUT_VERSION",
    "ActiveThread",
    "AgentMessage",
    "CapabilityDefinition",
    "CapabilityView",
    "CharacterStateSnapshot",
    "ContextRequest",
    "ContextSnapshotV2",
    "ContextSourceSnapshot",
    "ConversationContinuity",
    "IdentityContext",
    "MemoryAccessPolicy",
    "MemoryContext",
    "MemoryItem",
    "RelationshipStateSnapshot",
    "SessionDigest",
    "SituationView",
    "SnapshotSourceVersion",
]
