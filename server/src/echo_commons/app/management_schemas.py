from datetime import datetime
from typing import Annotated, Literal
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, JsonValue, model_validator

from echo_commons.agents.contracts.context import ContextSnapshot, HistoricalThought, MemoryContext
from echo_commons.agents.contracts.recovery import FailureInfo, RecoveryAction
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.contracts.run import AgentRunResult, AgentRunStatus
from echo_commons.app.http import RequestModel
from echo_commons.execution.observations import EventKind, ExecutionEventPayload
from echo_commons.modules.assets.contracts import GenerationView
from echo_commons.modules.characters.api.authoring_schemas import CandidateView
from echo_commons.modules.characters.api.schemas import CharacterView
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.conversations.api.schemas import ConversationView, MessageView
from echo_commons.modules.conversations.domain.task import TaskStatus
from echo_commons.modules.memory.domain.organization import MemoryRecordRef
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.perspective.contracts import ConversationBoundary
from echo_commons.modules.reflection.contracts.context import (
    GraphContextSnapshot,
    NonThoughtMaterial,
    ReflectionNodeInput,
    ThoughtMaterial,
)
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind, ReflectionGraphRun
from echo_commons.modules.reflection.domain.node import ReflectionNodeTask
from echo_commons.shared.actors import ActorKind, ActorRef
from echo_commons.shared.management import Page


class View(BaseModel):
    model_config = ConfigDict(from_attributes=True)


class CommunityMemberView(View):
    community_id: str
    actor_kind: ActorKind
    actor_id: str
    joined_at_utc: datetime


class ManagementCharacterView(CharacterView):
    memory_error_code: str | None = None


class ManagementGenerationView(GenerationView):
    error_code: str | None
    provider_task_id: str | None
    deadline_utc: datetime


class ManagementCandidateView(CandidateView):
    error_code: str | None


class CoreRefreshRequest(RequestModel):
    request_id: UUID


class RelationshipRefreshRequest(CoreRefreshRequest):
    target: ActorRef | None = None


class RelationshipRefreshResult(View):
    target: ActorRef
    graph_run_id: str | None
    error_code: str | None
    source_version: str


class RelationshipRefreshProgress(View):
    graph_run_id: str | None
    status: str | None
    error_code: str | None
    source_version: str
    request_kind: Literal["automatic", "missing", "manual"]


class CoreRefreshProgress(View):
    graph_run_id: UUID | None
    status: str | None
    error_code: str | None
    outcome: Literal["completed", "no_op"] | None
    previous_core: str
    selected_memory_ids: list[str]
    unread_memory_ids: list[str]
    processed_count: int
    total_count: int
    sources_readable: bool


class CoreMemoryInspection(View):
    content: str
    source_refs: list[str]
    max_chars: int
    refresh: CoreRefreshProgress | None
    supporting_records: list[MemoryRecordRef]


class MemoryIndexFailure(BaseModel):
    source_kind: str
    source_id: str
    error_code: str
    provider_attempts: int
    recorded_at_utc: datetime


class MemoryIndexStatus(BaseModel):
    documents: int
    vectors: int
    vector_enabled: bool
    model_identity: str | None
    failures: list[MemoryIndexFailure]


class CharacterDetail(ManagementCharacterView):
    availability_reason: str | None
    next_check_at_utc: datetime | None
    updated_at_utc: datetime


class StateView(View):
    entry_id: str
    community_id: str
    character_id: str
    state_kind: StateKind
    value: str
    source_kind: str
    source_ref: str
    state_version: int
    recorded_at_utc: datetime
    expires_at_utc: datetime | None


class StateInspection(View):
    effective_at_utc: datetime
    current: list[StateView]
    history: Page[StateView]


class RelationshipInspection(View):
    community_id: str
    observer_character_id: str
    target_kind: ActorKind
    target_id: str
    relationship_type: Literal["stranger", "acquaintance", "friend"]
    affection: float | None
    trust: float | None
    attachment: float | None
    friend_qualifying_evidence_id: str | None
    attitude_summary: str
    attitude_source_refs: list[str]
    state_version: int
    updated_at_utc: datetime
    target_name: str
    attitude_refresh: RelationshipRefreshProgress | None


class EvidenceView(View):
    evidence_id: str
    community_id: str
    observer_character_id: str
    target_kind: ActorKind
    target_id: str
    evidence_kind: Literal["interaction", "support", "conflict", "commitment"]
    source_kind: str
    source_ref: str
    occurred_at_utc: datetime
    recorded_at_utc: datetime


class ConversationDetail(ConversationView):
    next_sequence: int


class MemberInterval(View):
    membership_id: str
    community_id: str
    conversation_id: str
    actor_kind: ActorKind
    actor_id: str
    joined_after_sequence: int
    left_at_sequence: int | None
    joined_at_utc: datetime
    left_at_utc: datetime | None


class MessageSummary(View):
    message_id: str
    community_id: str
    conversation_id: str
    sequence: int
    sender_kind: Literal["player", "character", "system"]
    sender_id: str
    text_preview: str
    visibility: Literal["conversation", "recipients"]
    source_turn_id: str | None
    result_id: str | None
    trace_id: str
    created_at_utc: datetime


class AudienceMember(View):
    membership_id: str
    actor_kind: ActorKind
    actor_id: str


class MessageDetail(MessageView):
    community_id: str
    result_id: str | None
    trace_id: str
    audience: list[AudienceMember]


class TurnSummary(View):
    social_turn_id: str
    community_id: str
    conversation_id: str
    visibility: Literal["conversation", "recipients"]
    status: Literal["pending", "running", "completed", "cancelled", "failed"]
    observation_max_sequence: int
    membership_version: int
    created_at_utc: datetime
    completed_at_utc: datetime | None
    chain_id: str | None = None
    parent_turn_id: str | None = None
    depth: int = 0
    policy_version: str | None = None
    stop_reason: str | None = None
    initiation_id: str | None = None


class SocialChainView(View):
    chain_id: str
    community_id: str
    conversation_id: str
    root_turn_id: str
    max_messages: int
    max_tasks: int
    message_count: int
    task_count: int
    status: Literal["active", "completed", "cancelled"]
    stop_reason: str | None
    created_at_utc: datetime
    completed_at_utc: datetime | None


class SocialCandidateView(View):
    social_turn_id: str
    character_id: str
    membership_id: str
    status: Literal["waiting", "excluded", "attempted", "skipped"]
    reason_code: str | None


class SocialTriggerView(View):
    input_batch_id: str
    chain_id: str
    origin_turn_id: str
    status: Literal["pending", "consumed", "discarded"]
    reason_code: str | None
    created_at_utc: datetime


class ParticipationDetail(View):
    character_id: str
    reason_code: str
    selection_order: int | None
    status: str
    outcome: str | None


class TurnDetail(TurnSummary):
    audience: list[str]
    completion: JsonValue
    participation: list[ParticipationDetail]
    task_ids: list[str]
    input_message_ids: list[str]
    chain: SocialChainView | None = None
    candidates: list[SocialCandidateView] = Field(default_factory=list)
    triggers: list[SocialTriggerView] = Field(default_factory=list)


class RecoverySummary(View):
    last_failure: FailureInfo | None = None
    last_recovery_action: RecoveryAction | None = None
    next_attempt_at_utc: datetime | None = None
    retry_exhausted: bool | None = None


class ExecutionEventView(View):
    event_id: int
    event_kind: EventKind
    task_kind: str
    task_id: str
    attempt: int
    lease_generation: int
    community_id: str
    character_id: str
    graph_run_id: str | None
    graph_execution_generation: int | None
    invocation_id: str | None
    trace_id: str
    recorded_at_utc: datetime
    payload: ExecutionEventPayload


class TaskSummary(RecoverySummary):
    task_id: str
    community_id: str
    conversation_id: str
    social_turn_id: str
    initiation_id: str | None = None
    character_id: str
    status: TaskStatus
    attempt_count: int
    lease_generation: int
    last_error_code: str | None
    trace_id: str
    created_at_utc: datetime
    updated_at_utc: datetime


class InspectedThought(HistoricalThought):
    content: str | None
    content_removed_at_utc: datetime | None = None


class InspectedMemory(MemoryContext):
    history_thoughts: tuple[InspectedThought, ...] = ()


class InspectedContext(ContextSnapshot):
    memory: InspectedMemory


class ConversationMessageContent(View):
    utterance: str
    thought: str | None = None
    reply_to: int | None = Field(default=None, ge=1)
    reply_to_message_id: str | None = None


class ConversationMessageOutput(View):
    contract: OutputContractRef
    payload: ConversationMessageContent


class ConversationMessageResult(AgentRunResult):
    status: Literal[AgentRunStatus.COMPLETED]
    output: ConversationMessageOutput = Field(...)


class ConversationSilentResult(AgentRunResult):
    status: Literal[AgentRunStatus.NO_PROPOSAL]
    output: None = None


class ConversationResultView(View):
    result_id: str
    task_id: str
    attempt_no: int
    lease_generation: int
    invocation_id: str
    output_contract: str
    status: Literal["pending", "approved", "rejected", "expired"]
    decision_code: str | None
    payload: Annotated[
        ConversationMessageResult | ConversationSilentResult, Field(discriminator="status")
    ]
    thought_removed_at_utc: datetime | None
    created_at_utc: datetime
    decided_at_utc: datetime | None


class ConversationInitiationView(View):
    initiation_id: str
    community_id: str
    conversation_id: str
    character_id: str
    request_id: str
    situation: str
    audience: list[str]
    created_at_utc: datetime


class TaskDetail(View):
    task: TaskSummary
    initiation: ConversationInitiationView | None = None
    context: InspectedContext
    results: list[ConversationResultView]
    recovery_history: Page[ExecutionEventView]


class SourceView(View):
    source_kind: str
    source_id: str
    source_version: str
    ordinal: int


class CoverageView(View):
    community_id: str
    character_id: str
    owner_kind: str
    owner_id: str
    source_kind: str
    source_id: str
    source_version: str


class ConsumptionView(View):
    segment_id: str
    summary_version: str
    batch_id: str
    outcome: Literal["completed", "no_op"]
    consumed_at_utc: datetime


class SegmentSceneView(View):
    conversation_id: str
    first_sequence: int
    last_sequence: int
    boundary: ConversationBoundary


class SegmentSummary(View):
    record_kind: Literal["segments"] = "segments"
    segment_id: str
    community_id: str
    character_id: str
    position: int
    started_at_utc: datetime
    ended_at_utc: datetime
    scenes: list[SegmentSceneView]
    status: Literal["sealed", "ingested"]
    source_version: str
    summary_version: str | None
    sealed_at_utc: datetime
    ingested_at_utc: datetime | None
    created_at_utc: datetime
    updated_at_utc: datetime


class SegmentDetail(SegmentSummary):
    summary_text: str | None
    sources: list[SourceView]
    context_sources: list[SourceView]
    consumption: list[ConsumptionView]
    coverage: list[CoverageView]


class BatchSource(View):
    ordinal: int
    segment_id: str
    summary_version: str


class BatchView(View):
    batch_id: str
    community_id: str
    character_id: str
    source_version: str
    previous_digest_ids: list[str]
    created_at_utc: datetime
    sources: list[BatchSource]


class DigestSummary(View):
    record_kind: Literal["digests"] = "digests"
    digest_id: str
    batch_id: str
    community_id: str
    character_id: str
    content_version: str
    covered_segments: list[str]
    created_at_utc: datetime


class DigestDetail(DigestSummary):
    content: str
    batch: BatchView


class LongTermSummary(View):
    memory_id: str
    community_id: str
    character_id: str
    topic: str
    version: int
    status: Literal["current", "superseded", "invalid", "needs_review"]
    salience: float
    source_kind: str
    source_ref: str
    recorded_at_utc: datetime


class RecordSourceView(View):
    source_kind: str
    source_id: str
    source_version: str
    readable: bool
    content: str | None


class FactSummary(LongTermSummary):
    record_kind: Literal["facts"] = "facts"
    participants: list[ActorRef]
    conditions: str
    occurred_at_utc: datetime | None
    learned_at_utc: datetime


class CognitionSummary(LongTermSummary):
    record_kind: Literal["cognitions"] = "cognitions"
    formed_at_utc: datetime | None
    applies_to: str
    target: ActorRef | None


class FactRevision(FactSummary):
    content: str
    sources: list[RecordSourceView]


class CognitionRevision(CognitionSummary):
    content: str
    sources: list[RecordSourceView]


class OrganizationStageView(View):
    stage: Literal["facts", "cognitions"]
    outcome: Literal["completed", "no_op"]
    completed_at_utc: datetime


class FactDetail(FactRevision):
    batch: BatchView | None
    versions: list[FactRevision]
    stages: list[OrganizationStageView]


class CognitionDetail(CognitionRevision):
    content: str
    batch: BatchView | None
    versions: list[CognitionRevision]
    stages: list[OrganizationStageView]


MemorySummary = Annotated[
    SegmentSummary | DigestSummary | FactSummary | CognitionSummary,
    Field(discriminator="record_kind"),
]
MemoryDetail = Annotated[
    SegmentDetail | DigestDetail | FactDetail | CognitionDetail,
    Field(discriminator="record_kind"),
]


class ReflectionSummary(RecoverySummary):
    graph_run_id: str
    community_id: str
    character_id: str
    graph_kind: ReflectionGraphKind
    graph_version: str
    status: Literal[
        "pending", "running", "retry_wait", "completed", "partial", "failed", "cancelled"
    ]
    execution_generation: int
    last_error_code: str | None
    trace_id: str | None
    created_at_utc: datetime
    updated_at_utc: datetime
    started_at_utc: datetime | None
    completed_at_utc: datetime | None


class InspectedThoughtMaterial(ThoughtMaterial):
    content: str | None
    content_removed_at_utc: datetime | None = None


class InspectedGraph(GraphContextSnapshot):
    memory: InspectedMemory
    materials: tuple[
        Annotated[
            NonThoughtMaterial | InspectedThoughtMaterial,
            Field(discriminator="kind"),
        ],
        ...,
    ]


class InspectedNode(ReflectionNodeInput):
    graph_snapshot: InspectedGraph


class NodeInspection(View):
    community_id: str
    character_id: str
    graph_run_id: str
    node_task_id: str
    input_ready: bool
    input: InspectedNode | None
    recovery_history: Page[ExecutionEventView]


class ArtifactView(View):
    artifact_id: str
    node_task_id: str
    attempt: int
    output_contract: dict[str, str]
    content_version: str
    payload: JsonValue
    audit: JsonValue
    evidence_refs: list[dict[str, str | None]]


class ReflectionResultView(View):
    result_id: UUID
    graph_run_id: UUID
    aggregate_fingerprint: str
    proposal: JsonValue
    status: str
    decision_code: str | None
    created_at_utc: datetime
    decided_at_utc: datetime | None


class TraceView(View):
    trace_id: str
    kind: str
    entity_type: str
    entity_id: str
    payload: JsonValue
    created_at_utc: datetime
    delivery_status: str
    last_error_code: str | None


class TraceInspection(View):
    correlation_id: str
    traces: list[TraceView]


class SupplementView(View):
    original_run_id: str
    retry_node_keys: list[str]


class ReflectionDetail(View):
    schema_version: Literal[1]
    supplement: SupplementView | None
    supplement_run_ids: list[str]
    graph_run: ReflectionGraphRun
    node_tasks: list[ReflectionNodeTask]
    recovery_summary: RecoverySummary
    node_recovery: dict[str, RecoverySummary]
    snapshot: dict[str, JsonValue]
    artifacts: list[ArtifactView]
    result: ReflectionResultView | None
    facts: list[dict[str, JsonValue]]
    traces: list[TraceView]


class SealResult(View):
    outcome: Literal["sealed", "no_material"]
    segment: SegmentDetail | None


class SegmentReflectionRequest(RequestModel):
    segment_id: str = Field(min_length=1)


class SummaryReflectionRequest(RequestModel):
    consumer: SummaryConsumer
    limit: int = Field(default=16, ge=1, le=200)


class ScheduleResult(View):
    outcome: Literal["scheduled", "existing", "no_material", "restarted"]
    graph_run: ReflectionSummary | None
    source_kind: str | None
    source_id: str | None


class ExportRequest(RequestModel):
    first_sequence: int = Field(ge=1)
    through_sequence: int = Field(ge=1)
    character_id: str | None = Field(default=None, min_length=1)

    @model_validator(mode="after")
    def bounded_range(self):
        if self.first_sequence > self.through_sequence:
            raise ValueError("first_sequence must not exceed through_sequence")
        if self.through_sequence - self.first_sequence >= 10000:
            raise ValueError("One export may include at most 10000 message sequences")
        return self


class ExportScope(View):
    community_id: str
    conversation_id: str
    character_id: str | None
    first_sequence: int
    through_sequence: int


class SourceReference(View):
    community_id: str
    character_id: str | None
    conversation_id: str | None
    source_kind: str
    source_id: str
    source_version: str | None


class ThoughtView(View):
    thought_id: str
    result_id: str
    community_id: str
    character_id: str
    conversation_id: str
    content: str | None
    content_version: str
    content_removed_at_utc: datetime | None
    created_at_utc: datetime


class ExportView(View):
    schema_version: Literal[1]
    scope: ExportScope
    exported_at_utc: datetime
    counts: dict[str, int]
    members: list[MemberInterval]
    messages: list[MessageDetail]
    turns: list[TurnSummary]
    tasks: list[TaskSummary]
    results: list[ConversationResultView]
    thoughts: list[ThoughtView]
    memory: list[MemoryDetail]
    references: list[SourceReference]
