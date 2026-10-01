from dataclasses import dataclass
from uuid import uuid4

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
from echo_commons.execution.workers.social import SocialWorker
from echo_commons.execution.workers.traces import TraceWorker
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.models.openai_compatible import OpenAICompatibleGateway
from echo_commons.infrastructure.models.registry import ModelRegistry, load_model_registry
from echo_commons.infrastructure.observability.debug_capture import AgentDebugCapture
from echo_commons.infrastructure.observability.trace_delivery import TraceDelivery
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.bootstrap import CharacterBootstrap
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.services.identity import CharacterIdentity
from echo_commons.modules.characters.services.registry import AgentRegistry
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
from echo_commons.modules.conversations.tasks.execution import (
    ConversationExecution,
    ExecutionLimits,
)
from echo_commons.modules.conversations.tasks.handler import ConversationHandler
from echo_commons.modules.conversations.tasks.lifecycle import TaskLifecycle
from echo_commons.modules.conversations.tasks.queue import ConversationQueue
from echo_commons.modules.conversations.tasks.review import ConversationReview, ReviewPolicy
from echo_commons.modules.memory.repositories.entries import MemoryEntryRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.memory.services.indexing import MemoryIndexing
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval
from echo_commons.modules.memory.tools.search import MemorySearchTool, memory_progress
from echo_commons.modules.perspective.conversation import ConversationPerspective
from echo_commons.modules.perspective.reader import WorldPerspective
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.planner import TurnPlanner
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
    started: bool = False


def assemble(settings: Settings) -> Application:
    database = Database(settings.database_path)
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
    outputs = OutputRegistry()
    outputs.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)
    tool = MemorySearchTool(database, retrieval)
    backend = HarnessBackend(
        model_budget,
        outputs=outputs,
        tools=(ToolRegistration(tool, memory_progress),),
        debug_capture=capture,
    )
    agents = AgentRegistry(instances, catalog, backend, capabilities, models.task_routing)
    context = ConversationContext(
        ContextPolicy(
            settings.recent_message_limit,
            settings.recent_message_max_chars,
            settings.resident_memory_limit,
            frozenset({"memory_search"}),
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
    workers = {"social": SocialWorker(planner)}
    for index in range(settings.model_concurrency):
        workers[f"conversations-{index}"] = ConversationWorker(
            TaskDispatcher(queue, registry, str(uuid4())), queue
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
    return Application(
        database,
        settings,
        catalog,
        models,
        gateway,
        community_service,
        CharacterBootstrap(database, catalog, communities, instances, states, entries),
        CharacterStateService(database, instances, states),
        conversation_service,
        intake,
        MessageQuery(database, conversations, messages, perspective),
        planner,
        queue,
        handler,
        supervisor,
        traces,
    )
