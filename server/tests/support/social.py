
from echo_commons.execution.records import ExecutionRecorder
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.relationships import RelationshipRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.tasks.context import ContextPolicy, ConversationContext
from echo_commons.modules.conversations.tasks.dispatch import ConversationTaskDispatcher
from echo_commons.modules.memory.repositories.initialization import InitializationRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.planner import TurnPlanner
from echo_commons.modules.social.repository import SocialRepository
from echo_commons.shared.actors import ActorRef
from support.messages import build_system


def build_planning_system(tmp_path, *, sql_directory=None):
    base = build_system(tmp_path, sql_directory=sql_directory)
    base.intake.quiet_seconds = 0
    with base.database.read() as connection:
        blueprint = base.characters.instances.get(connection, "community", "first").blueprint_id
    base.characters.create(
        "community", blueprint, character_id="third", player_id="alice", memory_mode="full"
    )
    base.conversations.join("community", "conversation", ActorRef("character", "third"))
    social, tasks = SocialRepository(), ConversationTaskRepository()
    context = ConversationContext(
        ContextPolicy(20, 6000, 32, frozenset({"memory_search"}), 4),
        base.catalog,
        CommunityRepository(),
        base.conversations.conversations,
        InstanceRepository(),
        StateRepository(),
        RelationshipRepository(),
        InitializationRepository(),
        MemoryProvenanceRepository(),
        base.world,
        base.retrieval,
        CapabilityResolver(frozenset({"memory_search"})),
    )
    base.social, base.tasks, base.completion = social, tasks, TurnCompletion(social)
    base.planner = TurnPlanner(
        base.database,
        CommunityRepository(),
        base.conversations.conversations,
        InstanceRepository(),
        base.messages,
        base.batches,
        social,
        ConversationTaskDispatcher(tasks, context, ExecutionRecorder(base.database)),
        base.perspective,
        base.completion,
    )
    return base


def send(system, text="一起讨论", *, mentions=()):
    return system.intake.send(
        "community",
        "conversation",
        PlayerMessage("alice", text, text, mentions=mentions),
    )
