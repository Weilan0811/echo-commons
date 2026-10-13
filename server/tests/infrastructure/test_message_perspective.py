from concurrent.futures import ThreadPoolExecutor
from datetime import UTC, datetime, timedelta
from types import SimpleNamespace

import pytest
from historical_messages import historical_message
from test_application_lifecycle import settings_for

from echo_commons.app.composition import assemble
from echo_commons.execution.records import ExecutionRecorder
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
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
from echo_commons.modules.perspective.contracts import ObservationScope
from echo_commons.modules.perspective.conversation import ConversationPerspective
from echo_commons.modules.perspective.reader import WorldPerspective
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.lifecycle import SocialLifecycle
from echo_commons.modules.social.repository import SocialRepository
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, NotFoundError


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


@pytest.fixture
def system(tmp_path):
    return build_system(tmp_path)


def send(system, text, *, player="alice", client=None, reply=None, mentions=()):
    return system.intake.send(
        "community",
        "conversation",
        PlayerMessage(player, client or text, text, mentions=mentions, reply_to_message_id=reply),
    )


def observed(system, character):
    with system.database.read() as connection:
        return system.perspective.messages(
            connection,
            ObservationScope("community", "conversation", ActorRef("character", character), 1000),
        )


def search(system, character, text):
    with system.database.read() as connection:
        return system.retrieval.search(
            connection,
            SearchScope("community", character, datetime.now(UTC), "conversation", 1000),
            text,
        )


def test_private_audience_filters_player_role_and_search(system):
    public = send(system, "大家讨论蓝色天空")
    private = historical_message(
        system, "秘密暗号橙色灯塔", recipients=(ActorRef("character", "first"),)
    )
    assert [item.message_id for item in observed(system, "first")] == [
        public.message_id,
        private.message_id,
    ]
    assert [item.message_id for item in observed(system, "second")] == [public.message_id]
    assert [
        item.message_id for item in system.query.read("community", "conversation", "alice").messages
    ] == [public.message_id, private.message_id]
    assert [
        item.message_id for item in system.query.read("community", "conversation", "bob").messages
    ] == [public.message_id]
    assert any(item.source_id == private.message_id for item in search(system, "first", "灯塔"))
    assert search(system, "second", "灯塔") == ()
    with system.database.transaction() as connection:
        system.index.rebuild(connection, "community", "second")
    assert search(system, "second", "灯塔") == ()


def test_public_observation_contains_names_without_private_state(system):
    send(system, "看见会话中的人物")
    with system.database.read() as connection:
        view = system.world.observe(
            connection,
            ObservationScope("community", "conversation", ActorRef("character", "first"), 1),
        )
    assert {participant.display_name for participant in view.participants} == {
        "alice",
        "bob",
        "小槿",
    }
    assert len(view.participants) == 4
    assert not hasattr(view, "mood") and not hasattr(view, "relationships")


def test_frozen_search_boundary_excludes_later_visible_messages(system):
    first = send(system, "观察边界内的灯塔")
    prepared = datetime.now(UTC)
    later = send(system, "观察边界之后的山峰")
    scope = SearchScope("community", "first", prepared, "conversation", first.sequence)
    with system.database.read() as connection:
        assert system.retrieval.search(connection, scope, "山峰") == ()
        assert all(
            hit.source_id != later.message_id
            for hit in system.retrieval.search(connection, scope, "灯塔")
        )


def test_invalidated_memory_is_not_recovered_from_old_index(system):
    from test_memory_records import prepare

    service, _, batch, facts, sources, now = prepare(system)
    with system.database.transaction() as connection:
        service.organize(
            connection, "community", "first", batch.batch_id, facts, (), sources, True, now, now
        )
    scope = SearchScope("community", "first", datetime.now(UTC), "conversation", 2)
    with system.database.read() as connection:
        hits = system.retrieval.search(connection, scope, "草莓")
        memory_id = next(hit.source_id for hit in hits if hit.source_kind == "memory_fact")
        before = system.retrieval.source_version(connection, scope)
    with system.database.transaction() as connection:
        connection.execute(
            "UPDATE memory_facts SET status='invalid' WHERE memory_id=?", (memory_id,)
        )
    with system.database.read() as connection:
        assert not any(
            hit.source_kind == "memory_fact"
            for hit in system.retrieval.search(connection, scope, "草莓")
        )
        with pytest.raises(ConflictError, match="memory_source_changed"):
            system.retrieval.search(connection, scope, "草莓", expected_source_version=before)


def test_author_originals_are_owned_by_character_scope(system):
    from echo_commons.modules.memory.services.materials import MemoryMaterials

    system.characters.create("community", "xiaojin", character_id="authored", memory_mode="simple")
    scope = SearchScope("community", "authored", datetime.now(UTC))
    with system.database.transaction() as connection:
        MemoryMaterials(system.index.search).authors(
            connection, "community", "authored", datetime.now(UTC)
        )
    with system.database.read() as connection:
        assert system.retrieval.search(connection, scope, "不见")
        assert (
            system.retrieval.search(
                connection, SearchScope("community", "first", datetime.now(UTC)), "不见"
            )
            == ()
        )


def test_join_leave_rejoin_preserves_exact_experiences(system):
    first = send(system, "过去看见月亮")
    system.conversations.leave("community", "conversation", ActorRef("character", "second"))
    absent = send(system, "离开期间看见太阳")
    system.conversations.join("community", "conversation", ActorRef("character", "second"))
    later = send(system, "回来以后看见星星")
    assert [item.message_id for item in observed(system, "second")] == [
        first.message_id,
        later.message_id,
    ]
    assert not search(system, "second", "太阳")
    with system.database.transaction() as connection:
        system.index.rebuild(connection, "community", "second")
    assert any(item.source_id == first.message_id for item in search(system, "second", "月亮"))
    assert all(item.source_id != absent.message_id for item in search(system, "second", "太阳"))
    system.characters.create("community", "xiaojin", character_id="new")
    system.conversations.join("community", "conversation", ActorRef("character", "new"))
    assert observed(system, "new") == ()
    with system.database.transaction() as connection:
        system.index.rebuild(connection, "community", "new")
    assert search(system, "new", "月亮") == ()


def test_idempotency_preserves_original_audience_after_departure(system):
    request = PlayerMessage("alice", "same", "一起谈论灯塔")
    original = system.intake.send("community", "conversation", request)
    system.conversations.leave("community", "conversation", ActorRef("player", "alice"))
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    assert system.intake.send("community", "conversation", request) == original
    with pytest.raises(ConflictError):
        send(system, request.text, client="same", mentions=(ActorRef("character", "second"),))
    with pytest.raises(ConflictError):
        send(system, "不同的正文", client="same")
    with system.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1


def test_reply_and_mentions_require_visibility_and_current_members(system):
    private = historical_message(system, "悄悄交流", recipients=(ActorRef("character", "first"),))
    with pytest.raises(NotFoundError):
        send(system, "不可见回复", player="bob", reply=private.message_id)
    with pytest.raises(NotFoundError):
        send(system, "不存在的提及对象", mentions=(ActorRef("player", "missing"),))
    message = send(
        system, "可见回复", reply=private.message_id, mentions=(ActorRef("character", "second"),)
    )
    assert message.reply_to_message_id == private.message_id


def test_cursor_advances_past_invisible_messages_and_binds_reader(system):
    first = send(system, "公开消息")
    private = historical_message(system, "私有消息", recipients=(ActorRef("character", "first"),))
    page = system.query.read("community", "conversation", "bob", limit=1)
    assert page.messages == (first,) and page.has_more
    next_page = system.query.read("community", "conversation", "bob", cursor=page.cursor, limit=1)
    assert next_page.messages == () and not next_page.has_more
    assert next_page.cursor != page.cursor
    assert (
        system.query.read("community", "conversation", "bob", cursor=next_page.cursor).messages
        == ()
    )
    with pytest.raises(ValueError):
        system.query.read("community", "conversation", "alice", cursor=next_page.cursor)
    with pytest.raises(ValueError):
        system.query.read("community", "conversation", "bob", cursor="invalid!")
    assert private.sequence == 2


def test_invisible_message_does_not_change_visible_source_version(system):
    send(system, "公开历史")
    with system.database.read() as connection:
        scope = SearchScope("community", "second", datetime.now(UTC), "conversation", 1000)
        before = system.retrieval.source_version(connection, scope)
    historical_message(system, "秘密内容", recipients=(ActorRef("character", "first"),))
    with system.database.read() as connection:
        after = system.retrieval.source_version(
            connection, SearchScope("community", "second", datetime.now(UTC), "conversation", 1000)
        )
    assert before == after


def test_interleaved_messages_have_exact_input_sources(system):
    first = send(system, "甲的第一句话")
    second = send(system, "乙的话", player="bob")
    third = send(system, "甲的第二句话")
    with system.database.read() as connection:
        sources = connection.execute(
            "SELECT bm.message_id FROM input_batch_messages bm JOIN input_batches b "
            "ON b.input_batch_id = bm.input_batch_id WHERE b.sender_id = 'alice'"
        ).fetchall()
        assert {row[0] for row in sources} == {first.message_id, third.message_id}
        assert second.message_id not in {row[0] for row in sources}
        assert connection.execute("SELECT COUNT(*) FROM input_batches").fetchone()[0] == 2


def test_expired_batch_is_sealed_before_next_message(system):
    first = send(system, "第一段输入")
    with system.database.transaction() as connection:
        connection.execute(
            "UPDATE input_batches SET quiet_until_utc = ?",
            (utc_text(datetime.now(UTC) - timedelta(seconds=1)),),
        )
    second = send(system, "第二段输入")
    with system.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM input_batches").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM input_batches WHERE status = 'sealed'"
            ).fetchone()[0]
            == 1
        )
        assert (
            connection.execute(
                "SELECT input_batch_id FROM input_batch_messages WHERE message_id = ?",
                (first.message_id,),
            ).fetchone()[0]
            != connection.execute(
                "SELECT input_batch_id FROM input_batch_messages WHERE message_id = ?",
                (second.message_id,),
            ).fetchone()[0]
        )


def test_parallel_intake_allocates_sequences_and_client_ids_once(system):
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(
            executor.map(lambda _: send(system, "重复请求", client="duplicate"), range(3))
        )
    assert len({message.message_id for message in results}) == 1
    with ThreadPoolExecutor(max_workers=3) as executor:
        results = list(
            executor.map(
                lambda index: send(system, f"并行输入 {index}", client=f"unique-{index}"), range(3)
            )
        )
    assert {message.sequence for message in results} == {2, 3, 4}
    with system.database.read() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM trace_outbox").fetchone()[0] == 4
        assert all(
            "text" not in row[0]
            for row in connection.execute("SELECT payload_json FROM trace_outbox")
        )
