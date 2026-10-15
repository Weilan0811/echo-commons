from echo_commons.execution.records import ExecutionRecorder
from echo_commons.execution.recovery import QueuePolicy
from echo_commons.modules.characters.domain.authoring import AuthoringContent
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.services.context import CharacterContext
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.repositories.records import LongTermMemoryRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository
from echo_commons.modules.reflection.contexts.graph import ReflectionContextPolicy
from echo_commons.modules.reflection.contexts.segment import SegmentContext
from echo_commons.modules.reflection.contexts.summaries import SummaryContext
from echo_commons.modules.reflection.coordinator import ReflectionCoordinator
from echo_commons.modules.reflection.registry import ReflectionGraphRegistry
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.queue import ReflectionQueue
from echo_commons.shared.actors import ActorRef
from support.historical_messages import historical_message
from support.memory import sealing
from support.messages import build_system, send
from support.recovery import reflection_recovery


def build_reflection(system):
    policy = ReflectionContextPolicy(frozenset({"memory_search"}), 32, 256, 20000)
    context = SegmentContext(
        policy,
        CharacterContext(
            system.catalog,
            InstanceRepository(),
            StateRepository(),
            RelationshipRepository(),
            system.world,
            CapabilityResolver(frozenset({"memory_search"})),
        ),
        CommunityRepository(),
        ConversationRepository(),
        system.world,
        LongTermMemoryRepository(),
        SegmentRepository(),
        ThoughtRepository(),
        system.retrieval,
    )
    coordinator = ReflectionCoordinator(
        system.database,
        ReflectionGraphRegistry(),
        SegmentRepository(),
        context,
        RunRepository(),
        NodeRepository(),
        SummaryContext(context.graph, MemoryProvenanceRepository(), context),
        ExecutionRecorder(system.database),
    )
    return context, coordinator


def prepare_queue(tmp_path, *, lease_seconds=30, max_attempts=3):
    system = build_system(tmp_path)
    send(system, "一起做一顿晚餐")
    context, coordinator = build_reflection(system)
    for character in ("first", "second"):
        segment = sealing(system).seal("community", character)
        coordinator.start_segment("community", character, segment.segment_id)
    queue = ReflectionQueue(
        system.database,
        NodeRepository(),
        RunRepository(),
        QueuePolicy(lease_seconds, max_attempts, 0),
        reflection_recovery(system.database, QueuePolicy(lease_seconds, max_attempts, 0)),
    )
    return system, context, coordinator, queue


def seed(application):
    application.communities.create("晚餐小组", "Asia/Shanghai", community_id="community")
    application.communities.update("community", expected_version=0, status="active")
    application.communities.register_player("玩家", player_id="player")
    application.communities.join("community", ActorRef("player", "player"))
    template = application.characters.catalog.catalog.blueprint("xiaojin")
    content = AuthoringContent(
        display_name=template.display_name,
        description="基础资料。",
        profile=template.profile.content,
        voice=template.voice.content,
        relational_dynamics=template.relational_dynamics.content,
    )
    draft, _ = application.authoring.create("player", "reflection-persona", content)
    draft = application.authoring.confirm_stage(
        "player", draft["draft_id"], draft["revision"], "basic"
    )
    draft = application.authoring.confirm_documents("player", draft["draft_id"], draft["revision"])
    blueprint, _ = application.authoring.confirm("player", draft["draft_id"], draft["revision"])
    for character in ("first", "second"):
        application.characters.create(
            "community",
            blueprint["blueprint_id"],
            player_id="player",
            character_id=character,
            memory_mode="full",
        )
    application.conversations.create(
        "community",
        "group",
        (
            ActorRef("player", "player"),
            ActorRef("character", "first"),
            ActorRef("character", "second"),
        ),
        conversation_id="conversation",
    )
    for character, secret in (("first", "草莓417"), ("second", "香蕉918")):
        historical_message(
            application,
            f"请记住晚餐暗号{secret}，只有你和我知道。",
            player="player",
            client=f"private-{character}",
            recipients=(ActorRef("character", character),),
        )
    application.intake.send(
        "community",
        "conversation",
        PlayerMessage(
            "player",
            "public",
            "我们现在已经开始一起准备晚餐。大家正愉快地协作做饭。"
            "我负责买菜，请你们帮忙准备米饭和蔬菜。记住现在的活动安排。",
            mentions=(ActorRef("character", "first"), ActorRef("character", "second")),
        ),
    )
    for character in ("first", "second"):
        segment = application.memory_sealing.seal("community", character)
        application.reflection.start_segment("community", character, segment.segment_id)
