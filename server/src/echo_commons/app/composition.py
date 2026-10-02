from dataclasses import dataclass
from uuid import uuid4

from pydantic import TypeAdapter

from echo_commons.agents.contracts.execution import ExecutionLimits
from echo_commons.agents.contracts.invocation import InvocationPurpose
from echo_commons.agents.contracts.output import (
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.agents.harness.runner import HarnessBackend
from echo_commons.agents.harness.tools import ToolRegistration
from echo_commons.app.settings import Settings
from echo_commons.execution.dispatcher import TaskDispatcher
from echo_commons.execution.model_budget import ModelBudget
from echo_commons.execution.recovery import QueuePolicy
from echo_commons.execution.registry import TaskRegistry
from echo_commons.execution.supervisor import Supervisor
from echo_commons.execution.workers.conversations import ConversationWorker
from echo_commons.execution.workers.reflection import ReflectionWorker
from echo_commons.execution.workers.social import SocialWorker
from echo_commons.execution.workers.traces import TraceWorker
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.models.openai_compatible import OpenAICompatibleGateway
from echo_commons.infrastructure.models.registry import ModelRegistry, load_model_registry
from echo_commons.infrastructure.observability.debug_capture import AgentDebugCapture
from echo_commons.infrastructure.observability.query import TraceQuery
from echo_commons.infrastructure.observability.trace_delivery import TraceDelivery
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.bootstrap import CharacterBootstrap
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.services.facts import (
    CharacterFacts,
    reflection_relationship_policy,
)
from echo_commons.modules.characters.services.identity import CharacterIdentity
from echo_commons.modules.characters.services.registry import AgentPurposeBinding, AgentRegistry
from echo_commons.modules.characters.services.state import CharacterStateService
from echo_commons.modules.characters.templates.catalog import BlueprintCatalog
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.communities.service import CommunityService
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.input_batches import InputBatchRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
from echo_commons.modules.conversations.repositories.results import ConversationResultRepository
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.services.batching import InputCollector
from echo_commons.modules.conversations.services.conversation import ConversationService
from echo_commons.modules.conversations.services.intake import MessageIntake
from echo_commons.modules.conversations.services.query import MessageQuery
from echo_commons.modules.conversations.tasks.commit import ConversationCommit
from echo_commons.modules.conversations.tasks.context import ContextPolicy, ConversationContext
from echo_commons.modules.conversations.tasks.diagnostics import ConversationDiagnostics
from echo_commons.modules.conversations.tasks.execution import (
    ConversationExecution,
)
from echo_commons.modules.conversations.tasks.handler import ConversationHandler
from echo_commons.modules.conversations.tasks.lifecycle import TaskLifecycle
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.modules.conversations.tasks.queue import ConversationQueue
from echo_commons.modules.conversations.tasks.review import ConversationReview, ReviewPolicy
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.repositories.organization import MemoryOrganizationRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.memory.services.batches import SummaryBatches
from echo_commons.modules.memory.services.bootstrap import MemoryBootstrap
from echo_commons.modules.memory.services.continuity import MemoryContinuity
from echo_commons.modules.memory.services.indexing import MemoryIndexing
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.memory.services.organization import MemoryOrganization
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval
from echo_commons.modules.memory.services.sealing import MemorySealing
from echo_commons.modules.memory.tools.search import MemorySearchTool, memory_progress
from echo_commons.modules.perspective.conversation import ConversationPerspective
from echo_commons.modules.perspective.reader import WorldPerspective
from echo_commons.modules.reflection.contexts.graph import ReflectionContextPolicy
from echo_commons.modules.reflection.contexts.segment import SegmentContext
from echo_commons.modules.reflection.contexts.summaries import SummaryContext
from echo_commons.modules.reflection.contracts.candidates import ReflectionNodeAction
from echo_commons.modules.reflection.contracts.context import REFLECTION_NODE_CONTRACT
from echo_commons.modules.reflection.coordinator import ReflectionCoordinator
from echo_commons.modules.reflection.diagnostics import ReflectionRunView
from echo_commons.modules.reflection.registry import ReflectionGraphRegistry
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.diagnostics import ReflectionDiagnosticsRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.results import ResultRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.commit import ReflectionNodeCommit
from echo_commons.modules.reflection.tasks.executor import ReflectionExecution
from echo_commons.modules.reflection.tasks.facts import ReflectionFacts
from echo_commons.modules.reflection.tasks.graph_commit import ReflectionGraphCommit
from echo_commons.modules.reflection.tasks.graph_review import GraphReview
from echo_commons.modules.reflection.tasks.handler import ReflectionHandler
from echo_commons.modules.reflection.tasks.prompt import project_node
from echo_commons.modules.reflection.tasks.queue import ReflectionQueue
from echo_commons.modules.reflection.tasks.readiness import ReflectionInputReadiness
from echo_commons.modules.reflection.tasks.review import ReflectionReview
from echo_commons.modules.reflection.workflow import ReflectionWorkflow
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.planner import TurnPlanner
from echo_commons.modules.social.query import TurnQuery
from echo_commons.modules.social.repository import SocialRepository


@dataclass
class Application:
    database: Database
    settings: Settings
    catalog: BlueprintCatalog
    models: ModelRegistry
    gateway: OpenAICompatibleGateway
    communities: CommunityService
    characters: CharacterBootstrap
    character_state: CharacterStateService
    conversations: ConversationService
    intake: MessageIntake
    messages: MessageQuery
    planner: TurnPlanner
    queue: ConversationQueue
    handler: ConversationHandler
    supervisor: Supervisor
    trace_delivery: TraceDelivery
    memory_sealing: MemorySealing
    segment_context: SegmentContext
    reflection: ReflectionCoordinator
    reflection_queue: ReflectionQueue
    reflection_execution: ReflectionExecution
    reflection_commit: ReflectionNodeCommit
    reflection_graph_commit: ReflectionGraphCommit
    summary_batches: SummaryBatches
    reflection_workflow: ReflectionWorkflow
    reflection_view: ReflectionRunView
    turns: TurnQuery
    conversation_diagnostics: ConversationDiagnostics
    trace_query: TraceQuery
    started: bool = False


def assemble(settings: Settings, *, read_only: bool = False) -> Application:
    database = Database(settings.database_path, read_only=read_only)
    catalog = load_blueprint_catalog(settings.identity_root)
    models = load_model_registry(settings.model_registry_path, settings.model_secrets_path)
    capture = AgentDebugCapture.from_settings(settings)
    gateway = OpenAICompatibleGateway(models, debug_capture=capture)
    model_budget = ModelBudget(gateway, settings.model_concurrency)
    communities = CommunityRepository()
    instances, states, relationships = (
        InstanceRepository(),
        StateRepository(),
        RelationshipRepository(),
    )
    conversations, messages = ConversationRepository(), MessageRepository()
    batches, tasks, queue_repository = (
        InputBatchRepository(),
        ConversationTaskRepository(),
        ConversationQueueRepository(),
    )
    entries, provenance, search = (
        MemoryEntryRepository(),
        MemoryProvenanceRepository(),
        SearchRepository(),
    )
    social = SocialRepository()
    completion = TurnCompletion(social)
    lifecycle = TaskLifecycle(tasks, completion)
    community_service = CommunityService(database, communities, lifecycle)
    conversation_service = ConversationService(database, communities, conversations, lifecycle)
    identity = CharacterIdentity(instances, catalog)
    perspective = ConversationPerspective(communities, conversations, messages)
    world = WorldPerspective(communities, identity, conversations, perspective)
    indexer = MemoryIndexing(instances, conversations, perspective, search, entries)
    retrieval = MemoryRetrieval(instances, conversations, entries, perspective, search)
    collector = InputCollector(batches)
    intake = MessageIntake(
        database,
        communities,
        conversations,
        messages,
        perspective,
        collector,
        indexer,
        quiet_seconds=settings.quiet_window_seconds,
    )
    capabilities = CapabilityResolver(frozenset({"memory_search"}))
    context = ConversationContext(
        ContextPolicy(
            settings.recent_message_limit,
            settings.recent_message_max_chars,
            settings.resident_memory_limit,
            frozenset({"memory_search"}),
            settings.covered_message_overlap,
        ),
        catalog,
        communities,
        conversations,
        instances,
        states,
        relationships,
        entries,
        provenance,
        world,
        retrieval,
        capabilities,
    )
    segment_context = SegmentContext(
        ReflectionContextPolicy(
            frozenset({"memory_search"}),
            settings.resident_memory_limit,
            settings.reflection_max_materials,
            settings.reflection_max_material_chars,
        ),
        context.character_context,
        communities,
        conversations,
        world,
        entries,
        SegmentRepository(),
        ThoughtRepository(),
        retrieval,
    )
    reflection = ReflectionCoordinator(
        database,
        ReflectionGraphRegistry(),
        SegmentRepository(),
        segment_context,
        RunRepository(),
        NodeRepository(),
        SummaryContext(segment_context.graph, MemoryProvenanceRepository()),
    )
    readiness = ReflectionInputReadiness(
        database,
        NodeRepository(),
        RunRepository(),
        communities,
        instances,
        segment_context.sources,
    )
    outputs = OutputRegistry()
    outputs.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)
    outputs.register(REFLECTION_NODE_CONTRACT, TypeAdapter(ReflectionNodeAction))
    tool = MemorySearchTool(database, retrieval, max_results=settings.memory_search_max_results)
    backend = HarnessBackend(
        model_budget,
        outputs=outputs,
        projector=project_snapshot,
        tools=(ToolRegistration(tool, memory_progress),),
        debug_capture=capture,
    )
    reflection_backend = HarnessBackend(
        model_budget,
        outputs=outputs,
        input_readiness=readiness,
        projector=project_node,
        tools=(ToolRegistration(tool, memory_progress),),
        debug_capture=capture,
    )
    agents = AgentRegistry(
        instances,
        catalog,
        {
            InvocationPurpose.CONVERSATION_REPLY: AgentPurposeBinding(
                backend, (CHARACTER_MESSAGE_CONTRACT,)
            ),
            InvocationPurpose.REFLECTION: AgentPurposeBinding(
                reflection_backend, (REFLECTION_NODE_CONTRACT,)
            ),
        },
        capabilities,
        models.task_routing,
    )
    reflection_queue = ReflectionQueue(
        database,
        NodeRepository(),
        RunRepository(),
        QueuePolicy(
            settings.lease_seconds, settings.max_agent_attempts, settings.retry_backoff_seconds
        ),
    )
    reflection_execution = ReflectionExecution(
        database,
        NodeRepository(),
        RunRepository(),
        ArtifactRepository(),
        ReflectionGraphRegistry(),
        agents,
        ExecutionLimits(
            model_steps=settings.reflection_max_model_steps,
            model_requests=settings.reflection_max_model_requests,
            max_output_tokens=settings.reflection_max_output_tokens,
            temperature=settings.reflection_temperature,
            top_p=settings.reflection_top_p,
        ),
    )
    reflection_commit = ReflectionNodeCommit(
        database,
        reflection_queue,
        ArtifactRepository(),
        segment_context.sources,
        ReflectionReview(settings.reflection_max_output_chars),
    )
    reflection_graph_commit = ReflectionGraphCommit(
        database,
        reflection_queue,
        ArtifactRepository(),
        ResultRepository(),
        ReflectionGraphRegistry(),
        segment_context.sources,
        GraphReview(settings.reflection_max_candidates, settings.reflection_max_output_chars),
        ReflectionFacts(
            MemoryIngestion(SegmentRepository(), CoverageRepository()),
            CharacterFacts(
                instances, relationships, states, reflection_relationship_policy(), communities
            ),
            MemoryContinuity(provenance),
            MemoryOrganization(provenance, MemoryOrganizationRepository(), indexer),
        ),
    )
    planner = TurnPlanner(
        database,
        communities,
        conversations,
        instances,
        messages,
        batches,
        social,
        tasks,
        perspective,
        context,
        completion,
        maximum_responders=settings.max_responders,
    )
    policy = QueuePolicy(
        settings.lease_seconds, settings.max_agent_attempts, settings.retry_backoff_seconds
    )
    queue = ConversationQueue(database, queue_repository, social, completion, policy)
    review_policy = ReviewPolicy(settings.max_thought_length, settings.max_utterance_length)
    execution = ConversationExecution(
        database,
        tasks,
        agents,
        ExecutionLimits(
            max_output_tokens=settings.conversation_max_output_tokens,
            temperature=settings.conversation_temperature,
            top_p=settings.conversation_top_p,
            output_instructions=review_policy.instructions(),
        ),
    )
    commit = ConversationCommit(
        database,
        tasks,
        queue_repository,
        ConversationResultRepository(),
        ConversationReview(
            communities,
            instances,
            conversations,
            messages,
            perspective,
            review_policy,
        ),
        communities,
        conversations,
        messages,
        collector,
        indexer,
        ThoughtRepository(),
        social,
        completion,
        policy,
    )
    handler = ConversationHandler(
        execution,
        commit,
        queue,
        settings.lease_heartbeat_interval_seconds,
        settings.lease_safety_margin_seconds,
    )
    registry = TaskRegistry()
    registry.register("conversation_reply", handler)
    registry.register(
        "reflection",
        ReflectionHandler(
            reflection_execution,
            reflection_commit,
            reflection_graph_commit,
            reflection_queue,
            ReflectionGraphRegistry(),
            settings.lease_heartbeat_interval_seconds,
            settings.reflection_execution_timeout_seconds,
        ),
    )
    workers = {"social": SocialWorker(planner)}
    for index in range(settings.model_concurrency):
        workers[f"conversations-{index}"] = ConversationWorker(
            TaskDispatcher(queue, registry, str(uuid4())), queue
        )
        workers[f"reflection-{index}"] = ReflectionWorker(
            TaskDispatcher(reflection_queue, registry, str(uuid4())), reflection_queue
        )
    traces = TraceDelivery(
        database,
        batch_size=settings.trace_batch_size,
        lease_seconds=settings.trace_lease_seconds,
        max_attempts=settings.trace_max_attempts,
        retry_backoff_seconds=settings.trace_retry_backoff_seconds,
    )
    workers["traces"] = TraceWorker(traces)
    supervisor = Supervisor(
        workers,
        poll_seconds=settings.worker_poll_interval_seconds,
        shutdown_seconds=settings.shutdown_timeout_seconds,
    )
    summary_batches = SummaryBatches(
        database,
        instances,
        conversations,
        world,
        provenance,
        max_materials=settings.reflection_max_materials,
        max_chars=settings.reflection_max_material_chars,
    )
    return Application(
        database,
        settings,
        catalog,
        models,
        gateway,
        community_service,
        CharacterBootstrap(
            database,
            catalog,
            communities,
            instances,
            states,
            MemoryBootstrap(entries, indexer, communities),
        ),
        CharacterStateService(database, instances, states),
        conversation_service,
        intake,
        MessageQuery(database, conversations, messages, perspective),
        planner,
        queue,
        handler,
        supervisor,
        traces,
        MemorySealing(
            database,
            instances,
            conversations,
            perspective,
            SegmentRepository(),
            ThoughtRepository(),
            max_messages=settings.reflection_max_messages_per_segment,
            max_materials=settings.reflection_max_materials,
            max_material_chars=settings.reflection_max_material_chars,
        ),
        segment_context,
        reflection,
        reflection_queue,
        reflection_execution,
        reflection_commit,
        reflection_graph_commit,
        summary_batches,
        ReflectionWorkflow(reflection, summary_batches),
        ReflectionRunView(
            database,
            RunRepository(),
            NodeRepository(),
            ArtifactRepository(),
            ResultRepository(),
            ReflectionDiagnosticsRepository(),
        ),
        TurnQuery(database, conversations, messages, perspective, social),
        ConversationDiagnostics(database, tasks),
        TraceQuery(database),
    )
