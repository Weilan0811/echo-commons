from datetime import UTC, datetime
from types import SimpleNamespace

from echo_commons.app.composition import assemble
from echo_commons.execution.records import ExecutionRecorder
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.characters.domain.authoring import AuthoringContent
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.modules.characters.services.blueprints import BlueprintReader
from echo_commons.modules.characters.services.bootstrap import CharacterBootstrap
from echo_commons.modules.characters.services.identity import CharacterIdentity
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.communities.service import CommunityService
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.input_batches import InputBatchRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.services.batching import InputCollector
from echo_commons.modules.conversations.services.conversation import ConversationService
from echo_commons.modules.conversations.services.intake import MessageIntake
from echo_commons.modules.conversations.services.query import MessageQuery
from echo_commons.modules.conversations.tasks.dispatch import TaskCancellation
from echo_commons.modules.conversations.tasks.lifecycle import TaskLifecycle
from echo_commons.modules.memory.repositories.records import LongTermMemoryRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.services.bootstrap import MemoryBootstrap
from echo_commons.modules.memory.services.indexing import MemoryIndexing
from echo_commons.modules.memory.services.retrieval import MemoryRetrieval, SearchScope
from echo_commons.modules.perspective.conversation import ConversationPerspective
from echo_commons.modules.perspective.reader import WorldPerspective
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.lifecycle import SocialLifecycle
from echo_commons.modules.social.repository import SocialRepository
from echo_commons.shared.actors import ActorRef
from support.application import settings_for


def build_system(tmp_path, *, sql_directory=None):
    database = Database(tmp_path / "messages.sqlite3")
    initialize(database, sql_directory=sql_directory)
    community_repo = CommunityRepository()
    social = SocialRepository()
    completion = TurnCompletion(social)
    social_lifecycle = SocialLifecycle(
        social, completion, TaskCancellation(ExecutionRecorder(database))
    )
    lifecycle = TaskLifecycle(
        ConversationTaskRepository(),
        TurnCompletion(SocialRepository()),
        ExecutionRecorder(database),
        social_lifecycle,
    )
    communities = CommunityService(database, community_repo, lifecycle)
    communities.create("群聊", "Asia/Shanghai", community_id="community")
    communities.update("community", expected_version=0, status="active")
    for identity in ("alice", "bob"):
        communities.register_player(identity, player_id=identity)
        communities.join("community", ActorRef("player", identity))
    instances = InstanceRepository()
    conversation_repo, message_repo, batches = (
        ConversationRepository(),
        MessageRepository(),
        InputBatchRepository(),
    )
    perspective = ConversationPerspective(community_repo, conversation_repo, message_repo)
    search = SearchRepository()
    entries = LongTermMemoryRepository()
    index = MemoryIndexing(instances, conversation_repo, perspective, search, entries)
    catalog = BlueprintReader(load_blueprint_catalog())
    application = assemble(
        settings_for(tmp_path, workers=False).model_copy(
            update={"database_path": str(database.path)}
        )
    )
    template = catalog.catalog.blueprint("xiaojin")
    content = AuthoringContent(
        display_name=template.display_name,
        description="基础人物资料。",
        profile=template.profile.content,
        voice=template.voice.content,
        relational_dynamics=template.relational_dynamics.content,
    )
    draft, _ = application.authoring.create("alice", "perspective-persona", content)
    draft = application.authoring.confirm_stage(
        "alice", draft["draft_id"], draft["revision"], "basic"
    )
    draft = application.authoring.confirm_documents("alice", draft["draft_id"], draft["revision"])
    blueprint, _ = application.authoring.confirm("alice", draft["draft_id"], draft["revision"])
    characters = CharacterBootstrap(
        database,
        catalog,
        community_repo,
        instances,
        StateRepository(),
        MemoryBootstrap(index),
    )
    for identity in ("first", "second"):
        characters.create(
            "community",
            blueprint["blueprint_id"],
            character_id=identity,
            player_id="alice",
            memory_mode="full",
        )
    conversations = ConversationService(database, community_repo, conversation_repo, lifecycle)
    actors = (
        ActorRef("player", "alice"),
        ActorRef("player", "bob"),
        ActorRef("character", "first"),
        ActorRef("character", "second"),
    )
    conversations.create("community", "group", actors, conversation_id="conversation")
    intake = MessageIntake(
        database,
        community_repo,
        conversation_repo,
        message_repo,
        perspective,
        InputCollector(batches),
        index,
        social_lifecycle,
    )
    query = MessageQuery(database, conversation_repo, message_repo, perspective)
    retrieval = MemoryRetrieval(
        instances, conversation_repo, LongTermMemoryRepository(), perspective, search
    )
    world = WorldPerspective(
        community_repo,
        CharacterIdentity(instances, catalog),
        conversation_repo,
        perspective,
    )
    return SimpleNamespace(
        database=database,
        catalog=catalog,
        communities=communities,
        characters=characters,
        conversations=conversations,
        perspective=perspective,
        index=index,
        intake=intake,
        query=query,
        retrieval=retrieval,
        messages=message_repo,
        batches=batches,
        world=world,
        social=social,
        completion=completion,
        social_lifecycle=social_lifecycle,
    )


def send(system, text, *, player="alice", client=None, reply=None, mentions=()):
    return system.intake.send(
        "community",
        "conversation",
        PlayerMessage(player, client or text, text, mentions=mentions, reply_to_message_id=reply),
    )


def search(system, character, text):
    with system.database.read() as connection:
        return system.retrieval.search(
            connection,
            SearchScope("community", character, datetime.now(UTC), "conversation", 1000),
            text,
        )
