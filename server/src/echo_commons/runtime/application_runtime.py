"""Public facade for the deterministic conversation Runtime workflows."""

from __future__ import annotations

from collections.abc import Callable
from datetime import datetime
from uuid import UUID, uuid4

import aiosqlite

from echo_server.agents.contracts import (
    AgentInvocation,
    AgentRunResult,
    ProposalEnvelope,
    RunnableAgent,
)
from echo_server.config import Settings
from echo_server.domain.memory import MemorySegment
from echo_server.domain.messages import (
    ConversationSyncQuery,
    MessageBatch,
    MessageReceipt,
    SubmitMessageCommand,
    SyncMessagesQuery,
)
from echo_server.domain.task import ConversationTask
from echo_server.observability.reflection_run_view import ReflectionRunViewService
from echo_server.observability.trace import TraceQueryService
from echo_server.runtime.common import (
    decode_conversation_cursor,
    decode_cursor,
    encode_conversation_cursor,
    encode_cursor,
    normalize_payload_hash,
    utc_now,
)
from echo_server.runtime.conversation.commit import ConversationCommitService
from echo_server.runtime.conversation.execution import ConversationExecutionService
from echo_server.runtime.conversation.handler import ConversationTaskHandler
from echo_server.runtime.conversation.intake import ConversationIntakeService
from echo_server.runtime.conversation.preparation import ConversationPreparationService
from echo_server.runtime.conversation.sync import ConversationSyncService
from echo_server.runtime.dispatcher import (
    ConversationTaskStore,
    TaskDispatcher,
    TaskHandlerRegistry,
)
from echo_server.runtime.eligibility import OfflineResponseEligibility, ResponseEligibility
from echo_server.runtime.errors import (
    DatabaseUnavailableError,
    IdempotencyConflictError,
    InvalidAgentRunError,
    InvalidCursorError,
    LeaseHeartbeatError,
    LeaseLostError,
    RuntimeErrorBase,
    UnknownConversationError,
    UnsupportedCapabilityError,
)
from echo_server.runtime.input_preparation import InputPreparation, OfflineInputPreparation
from echo_server.runtime.lifecycle import RuntimeLifecycle
from echo_server.runtime.modules import (
    ConversationModule,
    MemoryModule,
    ObservabilityModule,
    ReflectionModule,
    RuntimeControls,
)
from echo_server.runtime.proposals import ProposalRegistry, ProposalReviewer
from echo_server.runtime.proposals.handlers import CharacterMessageHandler
from echo_server.runtime.reflection import (
    ContinuityCompressionTrigger,
    MemoryOrganizationTrigger,
    ReflectionCoordinator,
    ReflectionGraphCommitService,
    ReflectionGraphExecutor,
    ReflectionGraphRegistry,
    ReflectionGraphScheduler,
    ReflectionGraphTaskStore,
)
from echo_server.runtime.trace.delivery import TraceDeliveryService
from echo_server.services.context import (
    ContextSnapshotBuilder,
    ContextSnapshotSource,
    RepositoryContextSource,
)
from echo_server.services.identity import IdentityCatalog, load_identity_catalog
from echo_server.services.memory import (
    MemoryInitializationService,
    MemorySearchService,
    MemorySegmentSealingService,
)
from echo_server.store.database import Database
from echo_server.store.memory_provenance import MemoryProvenanceRepository
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


class ApplicationRuntime:
    """Compose the application modules used by the API and Workers."""

    def __init__(
        self,
        database: Database,
        agent: RunnableAgent,
        settings: Settings | None = None,
        *,
        clock: Callable[[], datetime] = utc_now,
        worker_id: str | None = None,
        eligibility: ResponseEligibility | None = None,
        input_preparation: InputPreparation | None = None,
        bubble_projector: Callable[[ProposalEnvelope], tuple[str, ...]] | None = None,
        identity_catalog: IdentityCatalog | None = None,
        memory_search: MemorySearchService | None = None,
        # test: 接收默认 Repository 来源并返回实际来源；留空时直接使用默认来源。
        context_source_factory: (
            Callable[[RepositoryContextSource], ContextSnapshotSource] | None
        ) = None,
    ) -> None:
        self.database = database
        self._settings = settings or Settings()
        self._agent = agent
        self._clock = clock
        self._worker_id = worker_id or f"worker-{uuid4()}"
        self._identity_catalog = identity_catalog or load_identity_catalog(
            self._settings.identity_root
        )
        self.controls = RuntimeControls(
            database=database,
            settings=self._settings,
            agent=agent,
            identity_catalog=self._identity_catalog,
            clock=clock,
            worker_id=self._worker_id,
            reflection_worker_id=f"{self._worker_id}-reflection",
            reflection_graph_worker_id=f"{self._worker_id}-reflection-graph",
            ensure_started=lambda: self.ensure_started(),
            error_code=self._error_code,
        )
        self._traces = TraceRepository(database)
        self.runtime_conversations = RuntimeConversationRepository(database)
        self.memory_search = memory_search or MemorySearchService(database)
        self.runtime_messages = RuntimeMessageRepository(
            database,
            search_index=self.memory_search,
        )
        self.input_batches = InputBatchRepository(database)
        self.runtime_tasks = ConversationTaskRepository(database)
        self.runtime_results = AgentResultRepository(database)
        self.world_states = WorldStateRepository(database)
        self.character_states = CharacterStateRepository(database)
        self.character_state_entries = CharacterStateEntryRepository(database)
        self.relationship_evidence = RelationshipEvidenceRepository(database)
        self.relationship_states = RelationshipStateRepository(database)
        self.memory_provenance = MemoryProvenanceRepository()
        self.memory_segments = MemorySegmentRepository(database)
        self.memory_entries = MemoryEntryRepository(
            database,
            search_index=self.memory_search,
        )
        self.diary_entries = DiaryEntryRepository(database)
        self.thoughts = ThoughtRepository(database)
        self.memory_graph = MemoryGraphRepository(database)
        self.memory_views = MemoryViewRepository(database)
        self.reflection_graph_runs = ReflectionGraphRunRepository(database)
        self.reflection_graph_nodes = ReflectionNodeTaskRepository(database)
        self.reflection_graph_artifacts = ReflectionArtifactRepository(database)
        self.reflection_graph_results = GraphReviewRepository(database)
        self.trace_query = TraceQueryService(self._traces)
        self.reflection_run_view = ReflectionRunViewService(
            database,
            graph_runs=self.reflection_graph_runs,
            node_tasks=self.reflection_graph_nodes,
            artifacts=self.reflection_graph_artifacts,
            results=self.reflection_graph_results,
            traces=self.trace_query,
        )
        self.observability = ObservabilityModule(
            self.controls,
            traces=self._traces,
            trace_query=self.trace_query,
            reflection_run_view=self.reflection_run_view,
        )
        self.reflection_graph_commit = None
        self.participants = ConversationParticipantRepository(database)
        self._response_eligibility = eligibility or OfflineResponseEligibility()
        self._input_preparation = input_preparation or OfflineInputPreparation()
        self._bubble_projector = bubble_projector or (
            lambda proposal: (proposal.payload.utterance,)
        )
        self.meta = MetaRepository(database)
        self.context_source = RepositoryContextSource(
            self.world_states,
            self.character_states,
            self.character_state_entries,
            self.relationship_states,
            self.memory_entries,
            resident_memory_limit=self.settings.resident_memory_limit,
        )
        if context_source_factory is not None:
            # test: 只在构造时选择来源；每次任务仍会通过它重新读取当前数据。
            self.context_source = context_source_factory(self.context_source)
        self.snapshot_builder = ContextSnapshotBuilder(
            self.runtime_messages,
            self.runtime_conversations,
            self.input_batches,
            self.identity_catalog,
            context_source=self.context_source,
            thoughts=self.thoughts,
        )
        self.memory_initialization = MemoryInitializationService(
            self.memory_entries,
            self.identity_catalog,
        )
        self.proposal_registry = ProposalRegistry(
            (
                CharacterMessageHandler(
                    max_utterance_length=self.settings.max_utterance_length,
                    max_thought_length=self.settings.max_thought_length,
                ),
            )
        )
        self.reviewer = ProposalReviewer(self.proposal_registry)
        self.memory_module = MemoryModule(
            self.controls,
            memory_search=self.memory_search,
            memory_segments=self.memory_segments,
            memory_entries=self.memory_entries,
            diary_entries=self.diary_entries,
            thoughts=self.thoughts,
            memory_views=self.memory_views,
            memory_graph=self.memory_graph,
            memory_initialization=self.memory_initialization,
        )
        self.conversation_module = ConversationModule(
            self.controls,
            observability=self.observability,
            memory=self.memory_module,
            runtime_conversations=self.runtime_conversations,
            runtime_messages=self.runtime_messages,
            input_batches=self.input_batches,
            runtime_tasks=self.runtime_tasks,
            runtime_results=self.runtime_results,
            world_states=self.world_states,
            character_states=self.character_states,
            character_state_entries=self.character_state_entries,
            relationship_evidence=self.relationship_evidence,
            relationship_states=self.relationship_states,
            participants=self.participants,
            response_eligibility=self._response_eligibility,
            input_preparation=self._input_preparation,
            bubble_projector=self._bubble_projector,
            meta=self.meta,
            snapshot_builder=self.snapshot_builder,
            proposal_registry=self.proposal_registry,
            reviewer=self.reviewer,
        )

        self.lifecycle = RuntimeLifecycle(self)
        self.trace_delivery = TraceDeliveryService(self.observability)
        self.observability.bind_delivery(self.trace_delivery)
        self.sync = ConversationSyncService(self.conversation_module)
        self.intake = ConversationIntakeService(self.conversation_module)
        self.conversation_module.intake = self.intake
        self.preparation = ConversationPreparationService(self.conversation_module)
        self.commit = ConversationCommitService(self.conversation_module)
        self.execution = ConversationExecutionService(self.conversation_module, self.commit)
        self.task_store = ConversationTaskStore(
            self.conversation_module,
            failure_scheduler=self.execution._schedule_task_failure,
        )
        self.task_registry = TaskHandlerRegistry()
        self.task_registry.register(ConversationTaskHandler(self.execution.run_task))
        self.dispatcher = TaskDispatcher(
            self.task_store,
            self.task_registry,
            worker_id=self.worker_id,
            # Resolve the Runtime clock at call time so deterministic tests and
            # embedded hosts can replace the clock after composition.
            clock=lambda: self.clock(),
        )
        self.reflection_graph_registry = ReflectionGraphRegistry()
        self.reflection_module = ReflectionModule(
            self.controls,
            observability=self.observability,
            memory=self.memory_module,
            context_source=self.context_source,
            reflection_graph_runs=self.reflection_graph_runs,
            reflection_graph_nodes=self.reflection_graph_nodes,
            reflection_graph_artifacts=self.reflection_graph_artifacts,
            reflection_graph_results=self.reflection_graph_results,
            character_state_entries=self.character_state_entries,
            relationship_evidence=self.relationship_evidence,
            relationship_states=self.relationship_states,
            runtime_messages=self.runtime_messages,
        )
        self.reflection_graph_coordinator = ReflectionCoordinator(
            self.reflection_module,
            registry=self.reflection_graph_registry,
        )
        self.reflection_module.reflection_graph_coordinator = self.reflection_graph_coordinator
        self.reflection_graph_commit = ReflectionGraphCommitService(self.reflection_module)
        self.reflection_module.reflection_graph_commit = self.reflection_graph_commit
        self.reflection_graph_scheduler = ReflectionGraphScheduler(self.reflection_module)
        self.reflection_module.reflection_graph_scheduler = self.reflection_graph_scheduler
        self.reflection_graph_task_store = ReflectionGraphTaskStore(self.reflection_module)
        self.reflection_module.reflection_graph_task_store = self.reflection_graph_task_store
        self.reflection_graph_task_registry = TaskHandlerRegistry()
        self.reflection_graph_executor = ReflectionGraphExecutor(
            self.reflection_module,
            self.reflection_graph_coordinator,
        )
        self.reflection_module.reflection_graph_executor = self.reflection_graph_executor
        self.reflection_graph_task_registry.register(self.reflection_graph_executor)
        self.reflection_graph_dispatcher = TaskDispatcher(
            self.reflection_graph_task_store,
            self.reflection_graph_task_registry,
            worker_id=self.reflection_graph_worker_id,
            clock=lambda: self.clock(),
        )
        self.reflection_module.reflection_graph_dispatcher = self.reflection_graph_dispatcher
        self.memory_sealing = MemorySegmentSealingService(
            database,
            self.runtime_conversations,
            self.runtime_messages,
            self.memory_segments,
            self.participants,
        )

    @property
    def settings(self) -> Settings:
        return self.controls.settings

    @settings.setter
    def settings(self, value: Settings) -> None:
        self._settings = value
        if hasattr(self, "controls"):
            self.controls.settings = value

    @property
    def response_eligibility(self) -> ResponseEligibility:
        if hasattr(self, "conversation_module"):
            return self.conversation_module.response_eligibility
        return self._response_eligibility

    @response_eligibility.setter
    def response_eligibility(self, value: ResponseEligibility) -> None:
        self._response_eligibility = value
        if hasattr(self, "conversation_module"):
            self.conversation_module.response_eligibility = value

    @property
    def input_preparation(self) -> InputPreparation:
        if hasattr(self, "conversation_module"):
            return self.conversation_module.input_preparation
        return self._input_preparation

    @input_preparation.setter
    def input_preparation(self, value: InputPreparation) -> None:
        self._input_preparation = value
        if hasattr(self, "conversation_module"):
            self.conversation_module.input_preparation = value

    @property
    def bubble_projector(self) -> Callable[[ProposalEnvelope], tuple[str, ...]]:
        if hasattr(self, "conversation_module"):
            return self.conversation_module.bubble_projector
        return self._bubble_projector

    @bubble_projector.setter
    def bubble_projector(
        self,
        value: Callable[[ProposalEnvelope], tuple[str, ...]],
    ) -> None:
        self._bubble_projector = value
        if hasattr(self, "conversation_module"):
            self.conversation_module.bubble_projector = value

    @property
    def traces(self) -> TraceRepository:
        return self.observability.traces

    @traces.setter
    def traces(self, value: TraceRepository) -> None:
        self._traces = value
        if hasattr(self, "observability"):
            self.observability.traces = value
            self.trace_query.repository = value

    @property
    def agent(self) -> RunnableAgent:
        return self.controls.agent

    @agent.setter
    def agent(self, value: RunnableAgent) -> None:
        self.controls.agent = value

    @property
    def identity_catalog(self) -> IdentityCatalog:
        return self.controls.identity_catalog

    @property
    def clock(self) -> Callable[[], datetime]:
        return self.controls.clock

    @clock.setter
    def clock(self, value: Callable[[], datetime]) -> None:
        self.controls.clock = value

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
    def wakeup(self):
        return self.controls.wakeup

    @wakeup.setter
    def wakeup(self, value) -> None:
        self.controls.wakeup = value

    @property
    def reflection_wakeup(self):
        return self.controls.reflection_wakeup

    @reflection_wakeup.setter
    def reflection_wakeup(self, value) -> None:
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

    async def start(self) -> None:
        await self.lifecycle.start()

    async def stop(self) -> None:
        await self.lifecycle.stop()

    async def ensure_started(self) -> None:
        await self.lifecycle.ensure_started()

    async def sync_messages(self, query: SyncMessagesQuery) -> MessageBatch:
        return await self.sync.sync_messages(query)

    async def sync_conversation_messages(
        self,
        query: ConversationSyncQuery,
    ) -> MessageBatch:
        return await self.sync.sync_conversation_messages(query)

    async def submit_message(self, command: SubmitMessageCommand) -> MessageReceipt:
        return await self.intake.submit_message(command)

    async def _seal_due_input_batches_in_transaction(
        self,
        account_id: str,
        conversation_id: str | None,
        now: datetime,
        correlation_id: UUID,
        connection: aiosqlite.Connection,
    ) -> int:
        return await self.intake._seal_due_input_batches_in_transaction(
            account_id,
            conversation_id,
            now,
            correlation_id,
            connection,
        )

    async def seal_due_input_batches(
        self,
        *,
        account_id: str | None = None,
        conversation_id: str | None = None,
    ) -> int:
        return await self.intake.seal_due_input_batches(
            account_id=account_id,
            conversation_id=conversation_id,
        )

    async def seal_unsegmented_messages(
        self,
        account_id: str,
        conversation_id: str,
        character_id: str,
        *,
        through_sequence: int | None = None,
        now_utc: datetime | None = None,
    ) -> MemorySegment | None:
        """Create one durable memory segment from uncovered messages."""

        await self.ensure_started()
        return await self.memory_sealing.seal_unsegmented_messages(
            account_id,
            conversation_id,
            character_id,
            through_sequence=through_sequence,
            now_utc=now_utc,
        )

    async def prepare_next_task(
        self,
        *,
        account_id: str | None = None,
        conversation_id: str | None = None,
    ) -> ConversationTask | None:
        return await self.preparation.prepare_next_task(
            account_id=account_id,
            conversation_id=conversation_id,
        )

    async def schedule_segment_reflection(
        self,
        segment_id: UUID,
        *,
        now_utc: datetime | None = None,
    ):
        """Create or return the graph for one sealed conversation segment."""

        started = await self.reflection_graph_scheduler.schedule_segment_reflection(
            segment_id,
            now_utc=now_utc,
        )
        return started

    async def schedule_memory_organization(
        self,
        trigger: MemoryOrganizationTrigger,
        *,
        now_utc: datetime | None = None,
    ):
        """Freeze the next summary batch and create its memory graph."""

        return await self.reflection_graph_scheduler.schedule_memory_organization(
            trigger,
            now_utc=now_utc,
        )

    async def schedule_continuity_compression(
        self,
        trigger: ContinuityCompressionTrigger,
        *,
        now_utc: datetime | None = None,
    ):
        """Freeze the next continuity batch and create its compression graph."""

        return await self.reflection_graph_scheduler.schedule_continuity_compression(
            trigger,
            now_utc=now_utc,
        )

    async def _event(
        self,
        correlation_id: UUID,
        kind: str,
        entity_type: str,
        entity_id: str,
        payload: dict,
    ) -> None:
        await self.observability.event(
            correlation_id,
            kind,
            entity_type,
            entity_id,
            payload,
        )

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

    @property
    def agent_traces(self):
        return self.observability.agent_traces

    @property
    def task_traces(self):
        return self.observability.task_traces

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

    def _trace_retry_delay(self, attempt_count: int) -> float:
        return self.trace_delivery._trace_retry_delay(attempt_count)

    @staticmethod
    def _error_code(error: Exception) -> str:
        return getattr(error, "code", None) or error.__class__.__name__.lower()


__all__ = [
    "ApplicationRuntime",
    "DatabaseUnavailableError",
    "IdempotencyConflictError",
    "InvalidAgentRunError",
    "InvalidCursorError",
    "LeaseHeartbeatError",
    "LeaseLostError",
    "RuntimeErrorBase",
    "UnknownConversationError",
    "UnsupportedCapabilityError",
    "decode_conversation_cursor",
    "decode_cursor",
    "encode_conversation_cursor",
    "encode_cursor",
    "normalize_payload_hash",
    "utc_now",
]
