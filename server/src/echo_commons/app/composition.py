from collections.abc import Mapping
from dataclasses import dataclass
from functools import partial
from uuid import uuid4

from echo_games.public import GameService
from pydantic import TypeAdapter

from echo_commons.agents.authoring import AuthoringAgent
from echo_commons.agents.contracts.activity import (
    ACTIVITY_EXPRESSION_CONTRACT,
    ACTIVITY_REPLY_CONTRACT,
    ACTIVITY_REPLY_SELECTION_CONTRACT,
    ActivityExpressionProposal,
    ActivityReplyProposal,
    ActivityReplySelection,
    ActivitySelection,
    ActivityTurnProposal,
    selection_contract,
    turn_contract,
)
from echo_commons.agents.contracts.execution import ExecutionLimits
from echo_commons.agents.contracts.invocation import InvocationPurpose
from echo_commons.agents.contracts.output import (
    CHARACTER_EXPRESSION_CONTRACT,
    CHARACTER_EXPRESSION_TYPE,
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.agents.harness.runner import HarnessBackend
from echo_commons.agents.harness.tools import ToolRegistration
from echo_commons.app.event_projection import EventProjection
from echo_commons.app.games.composition import assemble_games
from echo_commons.app.settings import Settings
from echo_commons.execution.dispatcher import TaskDispatcher
from echo_commons.execution.model_budget import ModelBudget
from echo_commons.execution.records import ExecutionRecorder
from echo_commons.execution.recovery import QueuePolicy, RecoveryPolicy
from echo_commons.execution.registry import TaskRegistry
from echo_commons.execution.supervisor import Supervisor
from echo_commons.execution.workers.activities import ActivityObservationWorker, ActivityWorker
from echo_commons.execution.workers.conversations import ConversationWorker
from echo_commons.execution.workers.images import ImageWorker
from echo_commons.execution.workers.reflection import ReflectionWorker
from echo_commons.execution.workers.social import SocialWorker
from echo_commons.execution.workers.traces import TraceWorker
from echo_commons.infrastructure.assets.storage import AssetStorage
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.game_analysis.rapfi.process import RapfiProcess
from echo_commons.infrastructure.models.budget import InputBudget
from echo_commons.infrastructure.models.decision import DecisionGateway
from echo_commons.infrastructure.models.embeddings import EmbeddingGateway
from echo_commons.infrastructure.models.images import ImageGateway
from echo_commons.infrastructure.models.openai_compatible import OpenAICompatibleGateway
from echo_commons.infrastructure.models.registry import ModelRegistry, load_model_registry
from echo_commons.infrastructure.observability.debug_capture import AgentDebugCapture
from echo_commons.infrastructure.observability.query import TraceQuery
from echo_commons.infrastructure.observability.trace_delivery import TraceDelivery
from echo_commons.infrastructure.realtime.stream import EventStream
from echo_commons.modules.activities.context import ActivityContext
from echo_commons.modules.activities.coordination import ActivityCoordinator
from echo_commons.modules.activities.expression import ActivityExpression, ExpressionRecovery
from echo_commons.modules.activities.gameplay.gomoku import GomokuAnalyzer
from echo_commons.modules.activities.gameplay.registry import GameplayRegistry
from echo_commons.modules.activities.lifecycle import ActivityLifecycle
from echo_commons.modules.activities.management import ActivityManagement
from echo_commons.modules.activities.observation import GameObservationService
from echo_commons.modules.activities.persona import ActivityPersona
from echo_commons.modules.activities.reactions import ActivityReactions
from echo_commons.modules.activities.repositories.expressions import ExpressionTasks
from echo_commons.modules.activities.repositories.results import ActivityResults
from echo_commons.modules.activities.repositories.sources import ActivitySources
from echo_commons.modules.activities.repositories.tasks import ActivityTasks
from echo_commons.modules.activities.tasks.commit import ActivityCommit
from echo_commons.modules.activities.tasks.execution import ActivityExecution
from echo_commons.modules.activities.tasks.handler import ActivityHandler
from echo_commons.modules.activities.tasks.prompt import project_activity
from echo_commons.modules.activities.tasks.queue import ActivityQueue
from echo_commons.modules.activities.tasks.readiness import ActivityReadiness
from echo_commons.modules.activities.tasks.recovery import ActivityRecovery
from echo_commons.modules.activities.tasks.review import ActivityReview
from echo_commons.modules.activities.tasks.scheduling import ActivitySchedulingQueue
from echo_commons.modules.activities.working_memory import ActivityWorkingMemory
from echo_commons.modules.assets.generation import ImageGenerations
from echo_commons.modules.assets.service import Assets
from echo_commons.modules.characters.management import CharacterManagement
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.authoring import CharacterAuthoring
from echo_commons.modules.characters.services.blueprints import BlueprintReader
from echo_commons.modules.characters.services.bootstrap import CharacterBootstrap
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.services.facts import (
    CharacterFacts,
    reflection_relationship_policy,
)
from echo_commons.modules.characters.services.identity import CharacterIdentity
from echo_commons.modules.characters.services.people import CharacterPeople
from echo_commons.modules.characters.services.registry import AgentPurposeBinding, AgentRegistry
from echo_commons.modules.characters.services.relationship_initialization import (
    CharacterRelationshipInitialization,
)
from echo_commons.modules.characters.services.state import CharacterStateService
from echo_commons.modules.characters.templates.catalog import BlueprintCatalog
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog
from echo_commons.modules.communities.events import CommunityEvents
from echo_commons.modules.communities.game_management import GameManagement
from echo_commons.modules.communities.game_participation import GameParticipationService
from echo_commons.modules.communities.game_query import GameSessionQuery
from echo_commons.modules.communities.management import CommunityManagement
from echo_commons.modules.communities.query import CommunityQuery
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.communities.service import CommunityService
from echo_commons.modules.conversations.export import ConversationExport
from echo_commons.modules.conversations.management import ConversationManagement
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.input_batches import InputBatchRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
from echo_commons.modules.conversations.repositories.results import ConversationResultRepository
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.services.batching import InputCollector
from echo_commons.modules.conversations.services.conversation import ConversationService
from echo_commons.modules.conversations.services.events import ConversationEvents
from echo_commons.modules.conversations.services.expression import ExpressionService
from echo_commons.modules.conversations.services.initiation import ConversationInitiation
from echo_commons.modules.conversations.services.intake import MessageIntake
from echo_commons.modules.conversations.services.player_query import PlayerConversationQuery
from echo_commons.modules.conversations.services.query import MessageQuery
from echo_commons.modules.conversations.tasks.commit import ConversationCommit
from echo_commons.modules.conversations.tasks.context import ContextPolicy, ConversationContext
from echo_commons.modules.conversations.tasks.diagnostics import ConversationDiagnostics
from echo_commons.modules.conversations.tasks.dispatch import (
    ConversationTaskDispatcher,
    TaskCancellation,
)
from echo_commons.modules.conversations.tasks.execution import (
    ConversationExecution,
)
from echo_commons.modules.conversations.tasks.handler import ConversationHandler
from echo_commons.modules.conversations.tasks.lifecycle import TaskLifecycle
from echo_commons.modules.conversations.tasks.memory import AutomaticMemory, budget_snapshot
from echo_commons.modules.conversations.tasks.prompt import participation_material, project_snapshot
from echo_commons.modules.conversations.tasks.queue import ConversationQueue
from echo_commons.modules.conversations.tasks.readiness import ConversationInputReadiness
from echo_commons.modules.conversations.tasks.recovery import ConversationRecovery
from echo_commons.modules.conversations.tasks.review import ConversationReview, ReviewPolicy
from echo_commons.modules.maintenance.service import Maintenance
from echo_commons.modules.memory.management import MemoryManagement
from echo_commons.modules.memory.repositories.changes import MemoryChangeRepository
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.initialization import InitializationRepository
from echo_commons.modules.memory.repositories.organization import MemoryOrganizationRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.records import LongTermMemoryRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.memory.services.batches import SummaryBatches
from echo_commons.modules.memory.services.bootstrap import MemoryBootstrap
from echo_commons.modules.memory.services.continuity import MemoryContinuity
from echo_commons.modules.memory.services.indexing import MemoryIndexing
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.memory.services.organization import MemoryOrganization
from echo_commons.modules.memory.services.preparation import MemoryPreparation
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval
from echo_commons.modules.memory.services.sealing import MemorySealing
from echo_commons.modules.memory.services.vectors import MemoryVectors
from echo_commons.modules.memory.services.views import MemoryViews
from echo_commons.modules.memory.tools.search import MemorySearchTool, memory_progress
from echo_commons.modules.perspective.conversation import ConversationPerspective
from echo_commons.modules.perspective.reader import WorldPerspective
from echo_commons.modules.reflection.context_preparation import ContextPreparation
from echo_commons.modules.reflection.contexts.graph import ReflectionContextPolicy
from echo_commons.modules.reflection.contexts.segment import SegmentContext
from echo_commons.modules.reflection.contexts.summaries import SummaryContext
from echo_commons.modules.reflection.contracts.candidates import (
    ExperienceModelAction,
    FactReviewModelAction,
    MemoryModelAction,
    ViewModelAction,
)
from echo_commons.modules.reflection.contracts.context import (
    FACT_REVIEW_NODE_CONTRACT,
    MEMORY_NODE_CONTRACT,
    REFLECTION_NODE_CONTRACT,
    VIEW_NODE_CONTRACT,
)
from echo_commons.modules.reflection.coordinator import ReflectionCoordinator
from echo_commons.modules.reflection.diagnostics import ReflectionRunView
from echo_commons.modules.reflection.initialization import FullMemoryInitialization
from echo_commons.modules.reflection.registry import ReflectionGraphRegistry
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.diagnostics import ReflectionDiagnosticsRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.results import ResultRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.scheduling import MemoryScheduling
from echo_commons.modules.reflection.tasks.commit import ReflectionNodeCommit
from echo_commons.modules.reflection.tasks.diagnosis import CandidateDiagnosis
from echo_commons.modules.reflection.tasks.executor import ReflectionExecution
from echo_commons.modules.reflection.tasks.facts import ReflectionFacts
from echo_commons.modules.reflection.tasks.graph_commit import ReflectionGraphCommit
from echo_commons.modules.reflection.tasks.graph_review import GraphReview
from echo_commons.modules.reflection.tasks.handler import ReflectionHandler
from echo_commons.modules.reflection.tasks.prompt import project_node
from echo_commons.modules.reflection.tasks.queue import ReflectionQueue
from echo_commons.modules.reflection.tasks.readiness import ReflectionInputReadiness
from echo_commons.modules.reflection.tasks.recovery import ReflectionRecovery
from echo_commons.modules.reflection.tasks.review import ReflectionReview
from echo_commons.modules.reflection.views import ViewScheduling
from echo_commons.modules.reflection.workflow import ReflectionWorkflow
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.continuation import ContinuationPolicy
from echo_commons.modules.social.dispatch import ResponseDispatcher
from echo_commons.modules.social.events import SocialEvents
from echo_commons.modules.social.judgment import SocialParticipation
from echo_commons.modules.social.lifecycle import SocialLifecycle
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
    community_management: CommunityManagement
    character_management: CharacterManagement
    conversation_management: ConversationManagement
    memory_management: MemoryManagement
    conversation_export: ConversationExport
    community_query: CommunityQuery
    player_conversations: PlayerConversationQuery
    authoring: CharacterAuthoring
    memory_indexing: MemoryIndexing
    realtime: EventStream
    assets: Assets
    image_generations: ImageGenerations
    maintenance: Maintenance
    games: GameService
    game_participation: GameParticipationService
    game_queries: GameSessionQuery
    game_observations: GameObservationService
    game_management: GameManagement
    conversation_initiations: ConversationInitiation
    conversation_expressions: ConversationCommit
    people: CharacterPeople
    game_analysis: GameplayRegistry
    rapfi: RapfiProcess
    activity_context: ActivityContext
    activity_working_memory: ActivityWorkingMemory
    activity_coordinator: ActivityCoordinator
    activity_queue: ActivityQueue
    activity_execution: ActivityExecution
    activity_commit: ActivityCommit
    activity_handler: ActivityHandler
    activity_expressions: ActivityExpression
    activity_reactions: ActivityReactions
    activity_lifecycle: ActivityLifecycle
    activity_management: ActivityManagement
    embeddings: EmbeddingGateway | None = None
    decisions: DecisionGateway | None = None
    started: bool = False


def assemble(
    settings: Settings,
    *,
    read_only: bool = False,
    prompt_examples: Mapping[str, str] | None = None,
) -> Application:
    database = Database(settings.database_path, read_only=read_only)
    rapfi = RapfiProcess(settings.game_analysis.rapfi)
    game_analysis = GameplayRegistry(
        (GomokuAnalyzer(rapfi),), max_attempts=settings.max_agent_attempts
    )
    catalog = load_blueprint_catalog(settings.identity_root)
    models = load_model_registry(settings.model_registry_path, settings.model_secrets_path)
    capture = AgentDebugCapture.from_settings(settings)
    gateway = OpenAICompatibleGateway(models, debug_capture=capture)
    model_budget = ModelBudget(gateway, settings.model_concurrency)
    decisions = (
        DecisionGateway(models, model_budget, debug_capture=capture)
        if models.decision.enabled
        else None
    )
    blueprint_reader = BlueprintReader(catalog)
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
        LongTermMemoryRepository(),
        MemoryProvenanceRepository(),
        SearchRepository(),
    )
    social = SocialRepository()
    completion = TurnCompletion(social)
    recorder = ExecutionRecorder(database)
    social_lifecycle = SocialLifecycle(social, completion, TaskCancellation(recorder))
    activity_sources = ActivitySources(social_lifecycle)
    policy = QueuePolicy(
        settings.lease_seconds, settings.max_agent_attempts, settings.retry_backoff_seconds
    )
    recovery_policy = RecoveryPolicy(policy)
    conversation_recovery = ConversationRecovery(
        recovery_policy, recorder, queue_repository, social_lifecycle
    )
    reflection_recovery = ReflectionRecovery(
        recovery_policy, recorder, NodeRepository(), RunRepository()
    )
    lifecycle = TaskLifecycle(tasks, completion, recorder, social_lifecycle)
    community_service = CommunityService(database, communities, lifecycle)
    conversation_service = ConversationService(database, communities, conversations, lifecycle)
    game_components = assemble_games(
        database, communities, conversation_service, conversations, instances
    )
    games, game_participation = game_components.games, game_components.participation
    identity = CharacterIdentity(instances, blueprint_reader)
    perspective = ConversationPerspective(communities, conversations, messages)
    world = WorldPerspective(communities, identity, conversations, perspective)
    indexer = MemoryIndexing(instances, conversations, perspective, search, entries)
    embeddings = (
        EmbeddingGateway(models, settings.memory.vector, model_budget)
        if settings.memory.vector.enabled
        else None
    )
    vectors = MemoryVectors(database, embeddings) if embeddings else None
    retrieval = MemoryRetrieval(
        instances, conversations, entries, perspective, search, vectors, settings.memory.retrieval
    )
    collector = InputCollector(batches)
    intake = MessageIntake(
        database,
        communities,
        conversations,
        messages,
        perspective,
        collector,
        indexer,
        social_lifecycle,
        game_participation,
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
            settings.memory.retrieval.automatic_limit,
            settings.memory.retrieval.automatic_max_chars,
            settings.memory.retrieval.input_max_chars,
        ),
        blueprint_reader,
        communities,
        conversations,
        instances,
        states,
        relationships,
        InitializationRepository(),
        provenance,
        world,
        retrieval,
        capabilities,
    )
    activity_working_memory = ActivityWorkingMemory(
        database, game_components.observations, conversations
    )
    activity_context = ActivityContext(
        database,
        game_components.observations,
        context,
        game_analysis,
        ActivityPersona(
            database,
            model_budget,
            models.route_for("activity_persona").resolved_profile,
            settings.activity,
        ),
        activity_working_memory,
        settings.activity,
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
        SummaryContext(segment_context.graph, MemoryProvenanceRepository(), segment_context),
        recorder,
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
    outputs.register(CHARACTER_EXPRESSION_CONTRACT, CHARACTER_EXPRESSION_TYPE)
    outputs.register(REFLECTION_NODE_CONTRACT, TypeAdapter(ExperienceModelAction))
    outputs.register(MEMORY_NODE_CONTRACT, TypeAdapter(MemoryModelAction))
    outputs.register(FACT_REVIEW_NODE_CONTRACT, TypeAdapter(FactReviewModelAction))
    outputs.register(VIEW_NODE_CONTRACT, TypeAdapter(ViewModelAction))
    tool = MemorySearchTool(database, retrieval, max_results=settings.memory_search_max_results)
    review_policy = ReviewPolicy(settings.max_thought_length, settings.max_utterance_length)
    entry = models.resolve(models.route_for("conversation_reply").resolved_profile)
    additional_limits = ()
    if models.decision.enabled:
        decision_entry = models.resolve(models.decision.profile)
        additional_limits = (
            InputBudget(
                model_entry_id=decision_entry.entry_id,
                context_window_tokens=decision_entry.context_window_tokens,
                output_tokens=decision_entry.max_output_tokens,
                token_counter=decision_entry.token_counter,
                max_chars=min(
                    settings.memory.retrieval.input_max_chars, models.decision.input_max_chars
                ),
                output_instructions=review_policy.instructions(),
            ),
        )
    context.input_budget = InputBudget(
        model_entry_id=entry.entry_id,
        context_window_tokens=entry.context_window_tokens,
        output_tokens=settings.conversation_max_output_tokens or 4096,
        token_counter=entry.token_counter,
        max_chars=settings.memory.retrieval.input_max_chars,
        tool_definitions=(tool.definition,),
        additional_limits=additional_limits,
        output_instructions=review_policy.instructions(),
    )
    context.memory_policy = settings.memory.context
    activity_tasks = ActivityTasks()
    expression_tasks = ExpressionTasks()
    activity_review = ActivityReview(game_components.observations, conversations, communities)
    activity_readiness = ActivityReadiness(database, activity_tasks, activity_review)
    activity_contracts = []
    outputs.register(ACTIVITY_REPLY_CONTRACT, ActivityReplyProposal)
    outputs.register(ACTIVITY_EXPRESSION_CONTRACT, ActivityExpressionProposal)
    outputs.register(ACTIVITY_REPLY_SELECTION_CONTRACT, ActivityReplySelection)
    for analyzer in game_analysis.analyzers:
        contract = turn_contract(analyzer.game_type)
        selected_contract = selection_contract(analyzer.game_type)
        if contract not in activity_contracts:
            outputs.register(contract, ActivityTurnProposal[analyzer.action_model])
            outputs.register(selected_contract, ActivitySelection[analyzer.action_model])
            activity_contracts.extend((contract, selected_contract))
    activity_backend = HarnessBackend(
        model_budget,
        outputs=outputs,
        projector=project_activity,
        input_readiness=activity_readiness,
        tools=(ToolRegistration(tool, memory_progress),),
        debug_capture=capture,
    )
    backend = HarnessBackend(
        model_budget,
        outputs=outputs,
        projector=project_snapshot,
        input_readiness=ConversationInputReadiness(database),
        tools=(ToolRegistration(tool, memory_progress),),
        debug_capture=capture,
    )
    reflection_backend = HarnessBackend(
        model_budget,
        outputs=outputs,
        input_readiness=readiness,
        projector=partial(project_node, examples=prompt_examples),
        tools=(ToolRegistration(tool, memory_progress),),
        debug_capture=capture,
    )
    agents = AgentRegistry(
        instances,
        blueprint_reader,
        {
            InvocationPurpose.ACTIVITY_EXPRESSION: AgentPurposeBinding(
                HarnessBackend(
                    model_budget,
                    outputs=outputs,
                    projector=project_activity,
                    input_readiness=ActivityReadiness(database, expression_tasks, activity_review),
                    tools=(ToolRegistration(tool, memory_progress),),
                    debug_capture=capture,
                ),
                (ACTIVITY_EXPRESSION_CONTRACT,),
            ),
            InvocationPurpose.ACTIVITY_TURN: AgentPurposeBinding(
                activity_backend, tuple(activity_contracts)
            ),
            InvocationPurpose.ACTIVITY_REPLY: AgentPurposeBinding(
                activity_backend, (ACTIVITY_REPLY_CONTRACT, ACTIVITY_REPLY_SELECTION_CONTRACT)
            ),
            InvocationPurpose.CONVERSATION_REPLY: AgentPurposeBinding(
                backend, (CHARACTER_MESSAGE_CONTRACT, CHARACTER_EXPRESSION_CONTRACT)
            ),
            InvocationPurpose.REFLECTION: AgentPurposeBinding(
                reflection_backend,
                (
                    REFLECTION_NODE_CONTRACT,
                    MEMORY_NODE_CONTRACT,
                    FACT_REVIEW_NODE_CONTRACT,
                    VIEW_NODE_CONTRACT,
                ),
            ),
        },
        capabilities,
        models.task_routing,
    )
    reflection_queue = ReflectionQueue(
        database,
        NodeRepository(),
        RunRepository(),
        policy,
        reflection_recovery,
    )
    from echo_commons.modules.reflection.budget import ReflectionBudget

    reflection_budget = ReflectionBudget(
        settings.reflection_max_candidates,
        settings.reflection_max_output_chars,
        settings.reflection_initialization_max_candidates,
        settings.reflection_initialization_max_output_chars,
        settings.reflection_initialization_chars_per_input_char,
        settings.reflection_initialization_candidates_per_material,
        settings.reflection_core_memory_max_chars,
        settings.reflection_relationship_attitude_max_chars,
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
        reflection_recovery,
        reflection_budget,
    )
    diagnosis = CandidateDiagnosis(
        reflection_queue,
        model_budget,
        outputs,
        readiness,
        settings.reflection_diagnosis,
        models.route_for("reflection_diagnosis").resolved_profile,
    )
    reflection_commit = ReflectionNodeCommit(
        database,
        reflection_queue,
        ArtifactRepository(),
        segment_context.sources,
        ReflectionReview(settings.reflection_max_output_chars, reflection_budget),
        diagnosis,
    )
    reflection_graph_commit = ReflectionGraphCommit(
        database,
        reflection_queue,
        ArtifactRepository(),
        ResultRepository(),
        ReflectionGraphRegistry(),
        segment_context.sources,
        GraphReview(
            settings.reflection_max_candidates,
            settings.reflection_max_output_chars,
            reflection_budget,
        ),
        ReflectionFacts(
            MemoryIngestion(SegmentRepository(), CoverageRepository()),
            CharacterFacts(
                instances,
                relationships,
                states,
                reflection_relationship_policy(),
                communities,
                MemoryChangeRepository(),
            ),
            MemoryContinuity(provenance),
            MemoryOrganization(provenance, MemoryOrganizationRepository(), indexer),
            MemoryViews(),
        ),
    )
    conversation_review = ConversationReview(
        communities,
        instances,
        conversations,
        messages,
        perspective,
        review_policy,
        game_participation,
    )
    participation = SocialParticipation(
        database,
        decisions,
        participation_material,
        queue_repository.owned,
        conversation_review.context,
    )
    response_dispatcher = ResponseDispatcher(
        ConversationTaskDispatcher(tasks, context, recorder, participation), activity_sources
    )
    social_lifecycle.tasks = response_dispatcher
    planner = TurnPlanner(
        database,
        communities,
        conversations,
        instances,
        messages,
        batches,
        social,
        response_dispatcher,
        perspective,
        completion,
        continuation=ContinuationPolicy(settings.max_chain_messages, settings.max_chain_tasks),
    )
    queue = ConversationQueue(
        database, queue_repository, social, completion, policy, conversation_recovery
    )
    activity_context.expression_permissions = planner.initiation_available
    execution = ConversationExecution(
        database,
        tasks,
        agents,
        ExecutionLimits(
            model_steps=3,
            model_requests=3,
            tool_calls=2,
            max_output_tokens=settings.conversation_max_output_tokens or 4096,
            max_input_chars=48000,
            temperature=settings.conversation_temperature,
            top_p=settings.conversation_top_p,
            output_instructions=review_policy.instructions(),
        ),
        conversation_recovery,
    )
    expression_service = ExpressionService(
        conversation_review,
        conversations,
        messages,
        collector,
        indexer,
        ThoughtRepository(),
        communities,
    )
    commit = ConversationCommit(
        database,
        tasks,
        queue_repository,
        ConversationResultRepository(),
        conversation_review,
        conversations,
        messages,
        social,
        conversation_recovery,
        social_lifecycle,
        expression_service,
    )
    handler = ConversationHandler(
        execution,
        commit,
        queue,
        settings.lease_heartbeat_interval_seconds,
        settings.lease_safety_margin_seconds,
        participation,
    )
    registry = TaskRegistry()
    registry.register("conversation_reply", handler, conversation_recovery.classify)
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
            diagnosis,
        ),
        reflection_recovery.classify,
    )
    workers = {"social": SocialWorker(planner)}
    activity_recovery = ActivityRecovery(
        recovery_policy, recorder, activity_tasks, activity_sources, activity_review
    )
    activity_lifecycle = ActivityLifecycle(
        database,
        game_components.observations,
        conversations,
        activity_review,
        activity_tasks,
        recorder,
        lifecycle,
        game_components.events,
        activity_sources,
    )
    activity_queue = ActivityQueue(
        database, activity_tasks, activity_recovery, policy, activity_lifecycle
    )
    activity_coordinator = ActivityCoordinator(
        database,
        activity_context,
        activity_tasks,
        decisions,
        models,
        activity_lifecycle,
        activity_sources,
    )
    activity_execution = ActivityExecution(
        database,
        activity_tasks,
        activity_context,
        agents,
        outputs,
        decisions,
        activity_readiness,
        activity_review,
        ExecutionLimits(
            max_output_tokens=settings.conversation_max_output_tokens,
            temperature=settings.conversation_temperature,
            top_p=settings.conversation_top_p,
        ),
        recorder,
    )
    activity_commit = ActivityCommit(
        database,
        activity_tasks,
        ActivityResults(),
        activity_context,
        game_participation,
        outputs,
        activity_review,
        activity_recovery,
        ThoughtRepository(),
        communities,
        activity_sources,
    )
    activity_expressions = ActivityExpression(
        database,
        expression_tasks,
        activity_context,
        activity_review,
        expression_service,
        planner,
        activity_sources,
        social_lifecycle,
        agents,
        outputs,
        activity_execution.limits,
        recorder,
    )
    expression_recovery = ExpressionRecovery(
        recovery_policy, recorder, expression_tasks, activity_sources, activity_review
    )
    expression_recovery.expressions = activity_expressions
    expression_queue = ActivityQueue(
        database, expression_tasks, expression_recovery, policy, activity_lifecycle
    )
    activity_expressions.queue = expression_queue
    activity_expressions.heartbeat_seconds = settings.lease_heartbeat_interval_seconds
    activity_lifecycle.expressions = activity_expressions
    activity_commit.expressions = activity_expressions
    initiations = ConversationInitiation(
        database, communities, conversations, instances, planner, game_participation
    )
    activity_reactions = ActivityReactions(
        database, activity_context, initiations, planner, settings.activity_reactions
    )
    activity_lifecycle.reactions = activity_reactions
    activity_handler = ActivityHandler(
        activity_execution,
        activity_commit,
        activity_queue,
        settings.lease_heartbeat_interval_seconds,
    )
    registry.register("activity_turn", activity_handler, activity_recovery.classify)
    registry.register("activity_reply", activity_handler, activity_recovery.classify)
    registry.register("activity_expression", activity_expressions, expression_recovery.classify)
    activity_scheduling = ActivitySchedulingQueue(
        activity_queue,
        expression_queue,
        task_weight=settings.activity_task_weight,
        expression_weight=settings.activity_expression_weight,
    )
    workers["activity-observation"] = ActivityObservationWorker(activity_reactions)
    if vectors:
        workers["memory-vectors"] = vectors
    for index in range(settings.model_concurrency):
        workers[f"activities-{index}"] = ActivityWorker(
            activity_coordinator,
            activity_scheduling,
            TaskDispatcher(activity_scheduling, registry, str(uuid4())),
        )
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
    dispatchers = tuple(
        worker.dispatcher
        for worker in workers.values()
        if isinstance(worker, ConversationWorker | ReflectionWorker | ActivityWorker)
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
    memory_sealing = MemorySealing(
        database,
        instances,
        conversations,
        world,
        SegmentRepository(),
        ThoughtRepository(),
        max_messages=settings.reflection_max_messages_per_segment,
        max_materials=settings.reflection_max_materials,
        max_material_chars=settings.reflection_max_material_chars,
        idle_seconds=settings.memory.cycles.experience_idle_seconds,
    )
    reflection_workflow = ReflectionWorkflow(reflection, summary_batches)
    context_preparation = ContextPreparation(
        context, memory_sealing, reflection_workflow, budget_snapshot
    )
    workers["conversation-memory"] = AutomaticMemory(
        database, retrieval, context_preparation, social_lifecycle, recorder
    )
    workers["memory-preparation"] = MemoryPreparation(database)
    relationship_initialization = CharacterRelationshipInitialization(
        database, model_budget, models.task_routing, MemoryChangeRepository()
    )
    workers["character-relationship-initialization"] = relationship_initialization
    workers["memory-initialization"] = FullMemoryInitialization(reflection)
    workers["memory-views"] = ViewScheduling(reflection)
    workers["memory-cycles"] = MemoryScheduling(
        memory_sealing, reflection_workflow, settings.memory.cycles
    )
    assets = Assets(database, AssetStorage(settings.asset_directory))
    image_gateway = ImageGateway(
        settings.image_base_url,
        models.credentials.get(settings.image_credential_ref),
        settings.image_request_timeout_seconds,
    )
    image_generations = ImageGenerations(database, image_gateway, settings)
    active_images = set()
    for slot in range(settings.image_concurrency):
        workers[f"image-generation-{slot}"] = ImageWorker(image_generations, assets, active_images)
    supervisor = Supervisor(
        workers,
        poll_seconds=settings.worker_poll_interval_seconds,
        shutdown_seconds=settings.shutdown_timeout_seconds,
    )
    message_query = MessageQuery(database, conversations, messages, perspective)
    player_query = PlayerConversationQuery(message_query, identity, game_participation)
    turn_query = TurnQuery(database, conversations, messages, perspective, social)
    realtime = EventStream(
        database,
        EventProjection(
            ConversationEvents(player_query),
            SocialEvents(turn_query),
            CommunityEvents(communities),
            game_components.events,
        ),
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
            blueprint_reader,
            communities,
            instances,
            states,
            MemoryBootstrap(indexer),
            relationship_initialization,
        ),
        CharacterStateService(database, instances, states),
        conversation_service,
        intake,
        message_query,
        planner,
        queue,
        handler,
        supervisor,
        traces,
        memory_sealing,
        segment_context,
        reflection,
        reflection_queue,
        reflection_execution,
        reflection_commit,
        reflection_graph_commit,
        summary_batches,
        reflection_workflow,
        ReflectionRunView(
            database,
            RunRepository(),
            NodeRepository(),
            ArtifactRepository(),
            ResultRepository(),
            ReflectionDiagnosticsRepository(),
        ),
        turn_query,
        ConversationDiagnostics(database, tasks),
        TraceQuery(database),
        CommunityManagement(database),
        CharacterManagement(database, identity),
        ConversationManagement(database),
        MemoryManagement(database),
        ConversationExport(database),
        CommunityQuery(database, identity),
        player_query,
        CharacterAuthoring(
            database,
            AuthoringAgent(
                model_budget,
                persona_examples=(
                    prompt_examples.get("persona_documents")
                    if prompt_examples is not None
                    else None
                ),
            ),
            models.task_routing,
        ),
        embeddings=embeddings,
        decisions=decisions,
        rapfi=rapfi,
        game_analysis=game_analysis,
        activity_context=activity_context,
        activity_working_memory=activity_working_memory,
        activity_coordinator=activity_coordinator,
        activity_queue=activity_queue,
        activity_execution=activity_execution,
        activity_commit=activity_commit,
        activity_handler=activity_handler,
        activity_expressions=activity_expressions,
        activity_reactions=activity_reactions,
        activity_lifecycle=activity_lifecycle,
        activity_management=ActivityManagement(
            database, activity_context, activity_tasks, ActivityResults(), recorder
        ),
        people=CharacterPeople(database, relationship_initialization),
        memory_indexing=indexer,
        realtime=realtime,
        assets=assets,
        image_generations=image_generations,
        games=games,
        game_participation=game_participation,
        game_queries=game_components.query,
        game_observations=game_components.observations,
        game_management=GameManagement(database, games),
        conversation_initiations=initiations,
        conversation_expressions=commit,
        maintenance=Maintenance(
            database,
            realtime.broker.notify,
            lambda: tuple(
                item.active_task_id for item in dispatchers if item.active_task_id is not None
            ),
            lambda: vectors.active_document_ids if vectors else frozenset(),
            assets=assets,
            active_generations=lambda: active_images.copy(),
        ),
    )
