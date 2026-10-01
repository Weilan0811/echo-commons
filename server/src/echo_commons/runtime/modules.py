from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime
from typing import TYPE_CHECKING
from uuid import UUID

import aiosqlite

from echo_server.agents.contracts import (
    AgentInvocation,
    AgentRunResult,
    ProposalEnvelope,
    RunnableAgent,
)
from echo_server.config import Settings
from echo_server.observability.reflection_run_view import ReflectionRunViewService
from echo_server.observability.trace import (
    AgentTraceRecorder,
    TaskTraceRecorder,
    TraceQueryService,
    safe_trace_payload,
)
from echo_server.runtime.eligibility import ResponseEligibility
from echo_server.runtime.input_preparation import InputPreparation
from echo_server.runtime.proposals import ProposalRegistry, ProposalReviewer
from echo_server.services.context import ContextSnapshotBuilder, ContextSnapshotSource
from echo_server.services.identity import IdentityCatalog
from echo_server.services.memory import MemoryInitializationService, MemorySearchService
from echo_server.store.database import Database
from echo_server.store.memory_repositories import (
    DiaryEntryRepository,
    MemoryEntryRepository,
    MemoryGraphRepository,
    MemorySegmentRepository,
    MemoryViewRepository,
    ThoughtRepository,
)
from echo_server.store.meta_repository import MetaRepository
from echo_server.store.reflection_graph_repositories import (
    GraphReviewRepository,
    ReflectionArtifactRepository,
    ReflectionGraphRunRepository,
    ReflectionNodeTaskRepository,
)
from echo_server.store.runtime_repositories import (
    AgentResultRepository,
    CharacterStateRepository,
    ConversationParticipantRepository,
    ConversationTaskRepository,
    InputBatchRepository,
    RuntimeConversationRepository,
    RuntimeMessageRepository,
    WorldStateRepository,
)
from echo_server.store.state_repositories import (
    CharacterStateEntryRepository,
    RelationshipEvidenceRepository,
    RelationshipStateRepository,
)
from echo_server.store.trace_repository import TraceRepository

if TYPE_CHECKING:
    from echo_server.runtime.conversation.intake import ConversationIntakeService
    from echo_server.runtime.dispatcher.dispatcher import TaskDispatcher
    from echo_server.runtime.reflection.coordinator import ReflectionCoordinator
    from echo_server.runtime.reflection.executor import ReflectionGraphExecutor
    from echo_server.runtime.reflection.facts import ReflectionGraphCommitService
    from echo_server.runtime.reflection.graph_queue import ReflectionGraphTaskStore
    from echo_server.runtime.reflection.workflow import ReflectionGraphScheduler
    from echo_server.runtime.trace.delivery import TraceDeliveryService


class RuntimeControls:
    def __init__(
        self,
        *,
        database: Database,
        settings: Settings,
        agent: RunnableAgent,
        identity_catalog: IdentityCatalog,
        clock: Callable[[], datetime],
        worker_id: str,
        reflection_worker_id: str,
        reflection_graph_worker_id: str,
        ensure_started: Callable[[], Awaitable[None]],
        error_code: Callable[[Exception], str],
    ) -> None:
        self.database = database
        self.settings = settings
        self.agent = agent
        self.identity_catalog = identity_catalog
        self.clock = clock
        self.worker_id = worker_id
        self.reflection_worker_id = reflection_worker_id
        self.reflection_graph_worker_id = reflection_graph_worker_id
        self.ensure_started_callback = ensure_started
        self.error_code = error_code
        self.wakeup: asyncio.Event | None = None
        self.reflection_wakeup: asyncio.Event | None = None
        self.started = False
        self.accepting_work = True

    async def ensure_started(self) -> None:
        await self.ensure_started_callback()


class ModuleBase:
    def __init__(self, controls: RuntimeControls) -> None:
        self.controls = controls

    @property
    def database(self) -> Database:
        return self.controls.database

    @property
    def settings(self) -> Settings:
        return self.controls.settings

    @property
    def agent(self) -> RunnableAgent:
        return self.controls.agent

    @property
    def identity_catalog(self) -> IdentityCatalog:
        return self.controls.identity_catalog

    @property
    def clock(self) -> Callable[[], datetime]:
        return self.controls.clock

    @property
    def worker_id(self) -> str:
        return self.controls.worker_id

    @property
    def reflection_worker_id(self) -> str:
        return self.controls.reflection_worker_id

    @property
    def reflection_graph_worker_id(self) -> str:
        return self.controls.reflection_graph_worker_id

    @property
    def wakeup(self) -> asyncio.Event | None:
        return self.controls.wakeup

    @wakeup.setter
    def wakeup(self, value: asyncio.Event | None) -> None:
        self.controls.wakeup = value

    @property
    def reflection_wakeup(self) -> asyncio.Event | None:
        return self.controls.reflection_wakeup

    @reflection_wakeup.setter
    def reflection_wakeup(self, value: asyncio.Event | None) -> None:
        self.controls.reflection_wakeup = value

    @property
    def started(self) -> bool:
        return self.controls.started

    @started.setter
    def started(self, value: bool) -> None:
        self.controls.started = value

    @property
    def accepting_work(self) -> bool:
        return self.controls.accepting_work

    @accepting_work.setter
    def accepting_work(self, value: bool) -> None:
        self.controls.accepting_work = value

    async def ensure_started(self) -> None:
        await self.controls.ensure_started()

    def _error_code(self, error: Exception) -> str:
        return self.controls.error_code(error)


class MemoryModule(ModuleBase):
    def __init__(
        self,
        controls: RuntimeControls,
        *,
        memory_search: MemorySearchService,
        memory_segments: MemorySegmentRepository,
        memory_entries: MemoryEntryRepository,
        diary_entries: DiaryEntryRepository,
        thoughts: ThoughtRepository,
        memory_views: MemoryViewRepository,
        memory_graph: MemoryGraphRepository,
        memory_initialization: MemoryInitializationService,
    ) -> None:
        super().__init__(controls)
        self.memory_search = memory_search
        self.memory_segments = memory_segments
        self.memory_entries = memory_entries
        self.diary_entries = diary_entries
        self.thoughts = thoughts
        self.memory_views = memory_views
        self.memory_graph = memory_graph
        self.memory_initialization = memory_initialization


class ObservabilityModule(ModuleBase):
    def __init__(
        self,
        controls: RuntimeControls,
        *,
        traces: TraceRepository,
        trace_query: TraceQueryService,
        reflection_run_view: ReflectionRunViewService,
    ) -> None:
        super().__init__(controls)
        self.traces = traces
        self.trace_query = trace_query
        self.reflection_run_view = reflection_run_view
        self._delivery: TraceDeliveryService | None = None

    def bind_delivery(self, delivery: TraceDeliveryService) -> None:
        self._delivery = delivery

    @property
    def delivery(self) -> TraceDeliveryService:
        if self._delivery is None:
            raise RuntimeError("observability delivery is not composed")
        return self._delivery

    @property
    def agent_traces(self) -> AgentTraceRecorder:
        return self.traces

    @property
    def task_traces(self) -> TaskTraceRecorder:
        return self.traces

    async def event(
        self,
        correlation_id: UUID,
        kind: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, object],
    ) -> None:
        await self.delivery.enqueue_event(correlation_id, kind, entity_type, entity_id, payload)

    async def record_agent_run_observations(
        self,
        invocation: AgentInvocation,
        result: AgentRunResult,
        *,
        entity_type: str,
        entity_id: str,
    ) -> None:
        for step in result.steps:
            await self.event(
                invocation.correlation.trace_id,
                "agent.step.completed",
                entity_type,
                entity_id,
                safe_trace_payload(
                    "agent.step.completed",
                    step_index=step.step_index,
                    response_kind=step.response_kind,
                    duration_ms=step.duration_ms,
                    tool_call_count=len(step.tool_activities),
                    model_request_count=1,
                    input_tokens=step.usage_summary.input_tokens,
                    cache_read_tokens=step.usage_summary.cache_read_tokens,
                    cache_write_tokens=step.usage_summary.cache_write_tokens,
                    output_tokens=step.usage_summary.output_tokens,
                    total_tokens=step.usage_summary.total_tokens,
                    progressed=(
                        any(activity.progressed for activity in step.tool_activities)
                        if step.tool_activities
                        else None
                    ),
                    new_item_count=sum(
                        activity.new_item_count for activity in step.tool_activities
                    ),
                ),
            )
            for activity in step.tool_activities:
                kind = "agent.tool.completed" if activity.ok else "agent.tool.failed"
                await self.event(
                    invocation.correlation.trace_id,
                    kind,
                    "agent_tool",
                    activity.call_id,
                    safe_trace_payload(
                        kind,
                        tool_name=activity.name,
                        ok=activity.ok,
                        error_code=activity.error_code,
                        duration_ms=activity.duration_ms,
                        progressed=activity.progressed,
                        new_item_count=activity.new_item_count,
                        no_progress_streak=activity.no_progress_streak,
                    ),
                )

    async def flush_trace_outbox(
        self,
        *,
        max_items: int | None = None,
        worker_id: str | None = None,
    ) -> int:
        return await self.delivery.flush_trace_outbox(
            max_items=max_items,
            worker_id=worker_id,
        )


class ConversationModule(ModuleBase):
    def __init__(
        self,
        controls: RuntimeControls,
        *,
        observability: ObservabilityModule,
        memory: MemoryModule,
        runtime_conversations: RuntimeConversationRepository,
        runtime_messages: RuntimeMessageRepository,
        input_batches: InputBatchRepository,
        runtime_tasks: ConversationTaskRepository,
        runtime_results: AgentResultRepository,
        world_states: WorldStateRepository,
        character_states: CharacterStateRepository,
        character_state_entries: CharacterStateEntryRepository,
        relationship_evidence: RelationshipEvidenceRepository,
        relationship_states: RelationshipStateRepository,
        participants: ConversationParticipantRepository,
        response_eligibility: ResponseEligibility,
        input_preparation: InputPreparation,
        bubble_projector: Callable[[ProposalEnvelope], tuple[str, ...]],
        meta: MetaRepository,
        snapshot_builder: ContextSnapshotBuilder,
        proposal_registry: ProposalRegistry,
        reviewer: ProposalReviewer,
    ) -> None:
        super().__init__(controls)
        self.observability = observability
        self.memory = memory
        self.runtime_conversations = runtime_conversations
        self.runtime_messages = runtime_messages
        self.input_batches = input_batches
        self.runtime_tasks = runtime_tasks
        self.runtime_results = runtime_results
        self.world_states = world_states
        self.character_states = character_states
        self.character_state_entries = character_state_entries
        self.relationship_evidence = relationship_evidence
        self.relationship_states = relationship_states
        self.participants = participants
        self.response_eligibility = response_eligibility
        self.input_preparation = input_preparation
        self.bubble_projector = bubble_projector
        self.meta = meta
        self.snapshot_builder = snapshot_builder
        self.proposal_registry = proposal_registry
        self.reviewer = reviewer
        self.intake: ConversationIntakeService | None = None

    @property
    def traces(self) -> TraceRepository:
        return self.observability.traces

    @property
    def agent_traces(self) -> AgentTraceRecorder:
        return self.observability.agent_traces

    @property
    def task_traces(self) -> TaskTraceRecorder:
        return self.observability.task_traces

    @property
    def memory_search(self) -> MemorySearchService:
        return self.memory.memory_search

    @property
    def memory_segments(self) -> MemorySegmentRepository:
        return self.memory.memory_segments

    @property
    def memory_entries(self) -> MemoryEntryRepository:
        return self.memory.memory_entries

    @property
    def diary_entries(self) -> DiaryEntryRepository:
        return self.memory.diary_entries

    @property
    def thoughts(self) -> ThoughtRepository:
        return self.memory.thoughts

    @property
    def memory_views(self) -> MemoryViewRepository:
        return self.memory.memory_views

    @property
    def memory_initialization(self) -> MemoryInitializationService:
        return self.memory.memory_initialization

    async def _event(
        self,
        correlation_id: UUID,
        kind: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, object],
    ) -> None:
        await self.observability.event(correlation_id, kind, entity_type, entity_id, payload)

    async def record_agent_run_observations(
        self,
        invocation: AgentInvocation,
        result: AgentRunResult,
        *,
        entity_type: str,
        entity_id: str,
    ) -> None:
        await self.observability.record_agent_run_observations(
            invocation,
            result,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    async def _seal_due_input_batches_in_transaction(
        self,
        account_id: str,
        conversation_id: str | None,
        now: datetime,
        correlation_id: UUID,
        connection: aiosqlite.Connection,
    ) -> int:
        if self.intake is None:
            raise RuntimeError("conversation intake is not composed")
        return await self.intake._seal_due_input_batches_in_transaction(
            account_id,
            conversation_id,
            now,
            correlation_id,
            connection,
        )


class ReflectionModule(ModuleBase):
    def __init__(
        self,
        controls: RuntimeControls,
        *,
        observability: ObservabilityModule,
        memory: MemoryModule,
        context_source: ContextSnapshotSource,
        reflection_graph_runs: ReflectionGraphRunRepository,
        reflection_graph_nodes: ReflectionNodeTaskRepository,
        reflection_graph_artifacts: ReflectionArtifactRepository,
        reflection_graph_results: GraphReviewRepository,
        character_state_entries: CharacterStateEntryRepository,
        relationship_evidence: RelationshipEvidenceRepository,
        relationship_states: RelationshipStateRepository,
        runtime_messages: RuntimeMessageRepository,
    ) -> None:
        super().__init__(controls)
        self.observability = observability
        self.memory = memory
        self.context_source = context_source
        self.reflection_graph_runs = reflection_graph_runs
        self.reflection_graph_nodes = reflection_graph_nodes
        self.reflection_graph_artifacts = reflection_graph_artifacts
        self.reflection_graph_results = reflection_graph_results
        self.character_state_entries = character_state_entries
        self.relationship_evidence = relationship_evidence
        self.relationship_states = relationship_states
        self.runtime_messages = runtime_messages
        self.reflection_graph_coordinator: ReflectionCoordinator | None = None
        self.reflection_graph_commit: ReflectionGraphCommitService | None = None
        self.reflection_graph_scheduler: ReflectionGraphScheduler | None = None
        self.reflection_graph_task_store: ReflectionGraphTaskStore | None = None
        self.reflection_graph_dispatcher: TaskDispatcher | None = None
        self.reflection_graph_executor: ReflectionGraphExecutor | None = None

    @property
    def traces(self) -> TraceRepository:
        return self.observability.traces

    @property
    def task_traces(self) -> TaskTraceRecorder:
        return self.observability.task_traces

    @property
    def agent_traces(self) -> AgentTraceRecorder:
        return self.observability.agent_traces

    @property
    def memory_search(self) -> MemorySearchService:
        return self.memory.memory_search

    @property
    def memory_segments(self) -> MemorySegmentRepository:
        return self.memory.memory_segments

    @property
    def memory_entries(self) -> MemoryEntryRepository:
        return self.memory.memory_entries

    @property
    def thoughts(self) -> ThoughtRepository:
        return self.memory.thoughts

    async def record_agent_run_observations(
        self,
        invocation: AgentInvocation,
        result: AgentRunResult,
        *,
        entity_type: str,
        entity_id: str,
    ) -> None:
        await self.observability.record_agent_run_observations(
            invocation,
            result,
            entity_type=entity_type,
            entity_id=entity_id,
        )

    async def flush_trace_outbox(
        self,
        *,
        max_items: int | None = None,
        worker_id: str | None = None,
    ) -> int:
        return await self.observability.flush_trace_outbox(
            max_items=max_items,
            worker_id=worker_id,
        )


__all__ = [
    "ConversationModule",
    "MemoryModule",
    "ModuleBase",
    "ObservabilityModule",
    "ReflectionModule",
    "RuntimeControls",
]
