import shutil
from concurrent.futures import ThreadPoolExecutor
from importlib.resources import files
from uuid import uuid4

import pytest
from echo_games.public import (
    CancelGameCommand,
    GameError,
    GameReadAccess,
    GameStatus,
    GomokuCreateGameCommand,
    GomokuResult,
    GomokuSubmitActionCommand,
    LeaveGameCommand,
    PlaceStoneAction,
    ResignGameCommand,
    StartGameCommand,
)
from fastapi.testclient import TestClient
from support.application import settings_for
from support.http import create_group
from support.migrations import load_history

from echo_commons.app.main import create_app
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.communities.contracts import (
    CreateGameSessionCommand,
    EndGameActivityCommand,
    JoinGameSessionCommand,
)
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.conversations.operations import ArchiveOperation, MembershipOperation
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, IdempotencyConflict, NotFoundError

ALICE = ActorRef("player", "alice")
BOB = ActorRef("player", "bob")


@pytest.fixture
def client(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"model_secrets_path": str(tmp_path / "absent-credentials.toml")}
    )
    with TestClient(create_app(settings)) as client:
        create_group(client, memory_mode="simple")
        yield client


def create(application, request_id="create"):
    return application.game_participation.create_game(
        ALICE,
        CreateGameSessionCommand(
            community_id="community", game=GomokuCreateGameCommand(request_id=request_id)
        ),
    )


def join(application, created, *, requester=BOB, request_id="join", version=1, seat="white"):
    command = JoinGameSessionCommand(
        game_id=created.game_id,
        request_id=request_id,
        expected_state_version=version,
        seat_id=seat,
        participant=requester,
    )
    return application.game_participation.join_game(requester, command)


def start(application, created):
    join(application, created)
    return application.game_participation.start_game(
        ALICE,
        StartGameCommand(game_id=created.game_id, request_id="start", expected_state_version=2),
    )


def summary(application, game_id):
    with application.database.read() as connection:
        return application.games.read_game(
            connection, GameReadAccess(game_id=game_id, requester_ref="player:alice")
        )


def message(application, created, text, *, actor=ALICE, **options):
    return application.intake.send(
        "community",
        created.conversation.conversation_id,
        PlayerMessage(
            player_id=actor.actor_id, client_message_id=uuid4().hex, text=text, **options
        ),
    )


def play(application, game_id, requester, x, y):
    with application.database.read() as connection:
        access = application.game_participation.seat_access(connection, requester, game_id)
        view = application.games.read_view(connection, access)
    opportunity = view.opportunities[0]
    command = GomokuSubmitActionCommand(
        request_id=uuid4().hex,
        opportunity_id=opportunity.opportunity_id,
        expected_state_version=view.state_version,
        action=PlaceStoneAction(x=x, y=y),
    )
    receipt = application.game_participation.submit_action(requester, game_id, command)
    return receipt, command


def end(application, created, *, request_id="end"):
    game = summary(application, created.game_id)
    conversation = application.conversation_management.conversation(
        "community", created.conversation.conversation_id
    )
    command = EndGameActivityCommand(
        game_id=created.game_id,
        request_id=request_id,
        expected_state_version=game.state_version,
        expected_conversation_version=conversation.state_version,
    )
    return application.game_participation.end_activity(ALICE, command), command


def test_create_join_real_game_finish_chat_and_end_preserve_receipts(client):
    application = client.app.state.application
    created = create(application)
    assert created.conversation.kind == "game"
    assert [member.actor for member in created.memberships] == [ALICE]
    started = start(application, created)
    assert started.game_receipt.state_version_after == 3
    assert create(application) == created
    receipt, command = play(application, created.game_id, ALICE, 0, 0)
    assert application.game_participation.submit_action(ALICE, created.game_id, command) == receipt
    for x in range(4):
        play(application, created.game_id, BOB, x, 1)
        play(application, created.game_id, ALICE, x + 1, 0)
    game = summary(application, created.game_id)
    assert game.status is GameStatus.FINISHED
    assert game.result == GomokuResult(reason="line", winner_seat_id="black")
    assert game.state_version == 12
    message(application, created, "这局下得很好")
    ended, end_command = end(application, created)
    assert ended.game_receipt is None
    assert ended.conversation.status == "archived"
    assert summary(application, created.game_id) == game
    assert application.game_participation.end_activity(ALICE, end_command) == ended
    assert application.game_participation.submit_action(ALICE, created.game_id, command) == receipt
    assert create(application) == created
    assert (
        application.game_participation.read_operation(ALICE, created.game_id, "create") == created
    )
    assert application.game_participation.read_operation(ALICE, created.game_id, "end") == ended
    assert application.game_participation.read_operation(BOB, created.game_id, "end") is None
    with pytest.raises(ConflictError):
        message(application, created, "结束后的新消息")
    with application.database.read() as connection:
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM game_operation_receipts WHERE game_id=?", (created.game_id,)
            ).fetchone()[0]
            == 3
        )


def test_leave_rejoin_and_seat_replacement_keep_original_history_and_retry(client):
    application = client.app.state.application
    created = create(application)
    joined = join(application, created)
    before = message(application, created, "双方都在场")
    old_participation = joined.game_receipt.result.participation.participation_id
    leave_command = LeaveGameCommand(
        game_id=created.game_id,
        request_id="leave",
        expected_state_version=2,
        participation_id=old_participation,
    )
    left = application.game_participation.leave_game(BOB, leave_command)
    gap = message(application, created, "只有创建者在场")
    with pytest.raises(NotFoundError):
        message(application, created, "离开后的新消息", actor=BOB)
    rejoined = join(application, created, request_id="rejoin", version=3)
    new_participation = rejoined.game_receipt.result.participation.participation_id
    assert new_participation != old_participation
    assert rejoined.memberships[0].membership_id != joined.memberships[0].membership_id
    assert application.game_participation.leave_game(BOB, leave_command) == left
    with pytest.raises(GameError, match="No current participation"):
        application.game_participation.leave_game(
            BOB,
            leave_command.model_copy(
                update={"request_id": "stale-leave", "expected_state_version": 4}
            ),
        )
    after = message(application, created, "重新加入之后")
    history = application.player_conversations.history(created.conversation.conversation_id, "bob")
    ids = {item["message_id"] for item in history["messages"]}
    assert before.message_id in ids and after.message_id in ids and gap.message_id not in ids
    with pytest.raises(NotFoundError):
        application.player_conversations.message(
            created.conversation.conversation_id, "bob", gap.message_id
        )
    with pytest.raises(NotFoundError):
        message(
            application, created, "回复不可见的消息", actor=BOB, reply_to_message_id=gap.message_id
        )
    application.game_participation.leave_game(
        BOB,
        LeaveGameCommand(
            game_id=created.game_id,
            request_id="leave-again",
            expected_state_version=4,
            participation_id=new_participation,
        ),
    )
    application.communities.register_player("第三位玩家", player_id="cara")
    cara = ActorRef("player", "cara")
    application.communities.join("community", cara)
    replacement = join(application, created, requester=cara, request_id="replace", version=5)
    assert replacement.game_receipt.result.participation.seat_id == "white"
    assert application.game_participation.leave_game(BOB, leave_command) == left
    assert summary(application, created.game_id).state_version == 6
    assert not application.player_conversations.history(
        created.conversation.conversation_id, "cara"
    )["messages"]


def test_creator_leaving_cancels_and_archives_with_repeatable_original_result(client):
    application = client.app.state.application
    created = create(application)
    join(application, created)
    command = LeaveGameCommand(
        game_id=created.game_id,
        request_id="creator-leave",
        expected_state_version=2,
        participation_id=created.game_receipt.result.participation.participation_id,
    )
    left = application.game_participation.leave_game(ALICE, command)
    assert left.game_receipt.status_after is GameStatus.CANCELLED
    assert left.conversation.status == "archived"
    assert summary(application, created.game_id).cancel_reason == "creator_left"
    assert application.game_participation.leave_game(ALICE, command) == left
    with pytest.raises(ConflictError):
        message(application, created, "归档后拒绝发言", actor=BOB)


def test_resignation_keeps_board_and_allows_chat_until_activity_ends(client):
    application = client.app.state.application
    created = create(application)
    started = start(application, created)
    play(application, created.game_id, ALICE, 7, 7)
    with application.database.read() as connection:
        access = application.game_participation.seat_access(connection, BOB, created.game_id)
    command = ResignGameCommand(
        game_id=created.game_id,
        request_id="resign",
        expected_state_version=4,
        participation_id=access.participation_id,
    )
    resigned = application.game_participation.resign_game(BOB, command)
    assert resigned.game_receipt.result.result == GomokuResult(
        reason="resignation", winner_seat_id="black"
    )
    assert resigned.conversation.status == "active"
    with application.database.read() as connection:
        view = application.games.read_view(connection, access)
        assert len(view.state.stones) == 1 and view.opportunities == ()
    message(application, created, "认输后仍可交流", actor=BOB)
    end(application, created)
    assert application.game_participation.resign_game(BOB, command) == resigned
    assert (
        application.game_participation.start_game(
            ALICE,
            StartGameCommand(game_id=created.game_id, request_id="start", expected_state_version=2),
        )
        == started
    )


@pytest.mark.parametrize("running", [False, True])
def test_cancel_blocks_new_chat_and_actions_but_preserves_history_and_retries(client, running):
    application = client.app.state.application
    created = create(application)
    if running:
        start(application, created)
    else:
        join(application, created)
    original = message(application, created, "取消前的消息", mentions=(BOB,))
    command = CancelGameCommand(
        game_id=created.game_id,
        request_id="cancel",
        expected_state_version=3 if running else 2,
        reason="players_cancelled",
    )
    cancelled = application.game_participation.cancel_game(ALICE, command)
    assert cancelled.conversation.status == "active"
    assert application.game_participation.cancel_game(ALICE, command) == cancelled
    with pytest.raises(ConflictError):
        message(application, created, "取消后不能继续发言", actor=BOB)
    old_request = PlayerMessage(
        player_id="alice",
        client_message_id=original.client_message_id,
        text=original.text,
        mentions=(BOB,),
    )
    assert (
        application.intake.send("community", created.conversation.conversation_id, old_request)
        == original
    )
    view = application.player_conversations.conversation(
        created.conversation.conversation_id, "bob"
    )
    assert not view["can_send"] and not view["can_join"] and not view["can_leave"]
    assert (
        application.player_conversations.message(
            created.conversation.conversation_id, "bob", original.message_id
        )["text"]
        == original.text
    )
    ended, _ = end(application, created)
    assert ended.game_receipt is None
    assert application.game_participation.cancel_game(ALICE, command) == cancelled
    with application.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM game_opportunities WHERE game_id=? AND status='open'",
                (created.game_id,),
            ).fetchone()[0]
            == 0
        )


@pytest.mark.parametrize("running", [False, True])
def test_end_unfinished_game_cancels_and_archives_in_one_operation(client, running):
    application = client.app.state.application
    created = create(application)
    if running:
        start(application, created)
    ended, command = end(application, created)
    assert ended.game_receipt.operation == "cancel"
    assert ended.game_receipt.result.reason == "activity_ended"
    assert ended.conversation.status == "archived"
    assert application.game_participation.end_activity(ALICE, command) == ended
    with pytest.raises(IdempotencyConflict):
        application.game_participation.end_activity(
            ALICE, command.model_copy(update={"expected_conversation_version": 2})
        )


def test_real_identity_seat_competition_versions_and_fixed_started_members(client):
    application = client.app.state.application
    created = create(application)
    with pytest.raises(GameError) as failure:
        application.game_participation.start_game(
            ALICE,
            StartGameCommand(
                game_id=created.game_id, request_id="too-early", expected_state_version=1
            ),
        )
    assert failure.value.code == "game_not_ready"
    with pytest.raises(GameError) as failure:
        join(application, created, requester=ALICE)
    assert failure.value.code == "participant_already_seated"
    with pytest.raises(GameError) as failure:
        application.game_participation.join_game(
            ALICE,
            JoinGameSessionCommand(
                game_id=created.game_id,
                request_id="impersonate",
                expected_state_version=1,
                seat_id="white",
                participant=BOB,
            ),
        )
    assert failure.value.code == "operation_forbidden"
    application.communities.register_player("第三位玩家", player_id="cara")
    cara = ActorRef("player", "cara")
    application.communities.join("community", cara)

    def compete(actor):
        try:
            return join(application, created, requester=actor, request_id=actor.actor_id)
        except GameError as error:
            return error

    with ThreadPoolExecutor(max_workers=2) as pool:
        results = list(pool.map(compete, (BOB, cara)))
    assert sum(not isinstance(result, GameError) for result in results) == 1
    assert summary(application, created.game_id).state_version == 2
    started = application.game_participation.start_game(
        ALICE,
        StartGameCommand(game_id=created.game_id, request_id="start", expected_state_version=2),
    )
    with pytest.raises(GameError) as failure:
        application.game_participation.leave_game(
            ALICE,
            LeaveGameCommand(
                game_id=created.game_id,
                request_id="late-leave",
                expected_state_version=3,
                participation_id=created.game_receipt.result.participation.participation_id,
            ),
        )
    assert failure.value.code == "game_already_started"
    assert (
        summary(application, created.game_id).state_version
        == started.game_receipt.state_version_after
    )


def test_regular_conversation_entries_cannot_change_game_members_or_archive(client):
    application = client.app.state.application
    created = create(application)
    identity = created.conversation.conversation_id
    for operation in (
        lambda: application.conversations.create("community", "game", (ALICE,), player_id="alice"),
        lambda: application.conversations.join("community", identity, BOB),
        lambda: application.conversations.leave("community", identity, ALICE),
        lambda: application.conversations.archive("community", identity),
        lambda: application.conversations.apply_membership(
            MembershipOperation(
                community_id="community",
                conversation_id=identity,
                action="join",
                actor=BOB,
                player_id="bob",
            ),
            uuid4().hex,
        ),
    ):
        with pytest.raises(ConflictError):
            operation()
    assert (
        client.put(
            f"/api/conversations/{identity}/membership",
            json={"player_id": "bob", "client_operation_id": uuid4().hex},
        ).status_code
        == 409
    )
    assert (
        client.post(
            f"/api/conversations/{identity}/archive",
            json={
                "player_id": "alice",
                "client_operation_id": uuid4().hex,
                "expected_state_version": 1,
            },
        ).status_code
        == 404
    )
    assert (
        client.post(
            "/api/communities/community/conversations",
            json={
                "player_id": "alice",
                "kind": "game",
                "actors": [{"kind": "player", "actor_id": "alice"}],
            },
        ).status_code
        == 422
    )
    with pytest.raises(NotFoundError):
        application.conversations.apply_list_operation(
            ArchiveOperation(
                community_id="community",
                conversation_id=identity,
                player_id="alice",
                expected_state_version=1,
            ),
            uuid4().hex,
        )
    assert summary(application, created.game_id).state_version == 1


def test_connection_business_methods_require_an_existing_transaction(client):
    application = client.app.state.application
    created = create(application)
    connection = application.database.connect()
    try:
        for operation in (
            lambda: application.conversations.create_in(connection, "community", "game", (ALICE,)),
            lambda: application.conversations.join_in(
                connection, "community", created.conversation.conversation_id, BOB
            ),
            lambda: application.conversations.leave_in(
                connection, "community", created.conversation.conversation_id, ALICE
            ),
            lambda: application.conversations.archive_in(
                connection, "community", created.conversation.conversation_id
            ),
        ):
            with pytest.raises(RuntimeError, match="caller-owned transaction"):
                operation()
    finally:
        connection.close()
    assert summary(application, created.game_id).state_version == 1


def test_chat_has_real_replies_mentions_audiences_events_and_no_normal_tasks(client):
    application = client.app.state.application
    created = create(application)
    join(application, created)
    original = message(application, created, "一起下棋", mentions=(BOB,))
    reply = message(
        application, created, "好的", actor=BOB, reply_to_message_id=original.message_id
    )
    view = application.player_conversations.message(
        created.conversation.conversation_id, "alice", reply.message_id
    )
    assert view["reply_preview"]["message_id"] == original.message_id
    with application.database.transaction() as connection:
        assert application.intake.batches.collect(connection, original, 0) is None
    assert application.planner.plan() == ()
    with application.database.read() as connection:
        for table in ("input_batches", "social_turns", "social_chains", "conversation_tasks"):
            assert (
                connection.execute(
                    f"SELECT COUNT(*) FROM {table} WHERE conversation_id=?",
                    (created.conversation.conversation_id,),
                ).fetchone()[0]
                == 0
            )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM message_recipients WHERE message_id=?", (original.message_id,)
            ).fetchone()[0]
            == 2
        )
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM realtime_events WHERE source_id=?", (original.message_id,)
            ).fetchone()[0]
            >= 1
        )
    application.intake.send(
        "community",
        "conversation",
        PlayerMessage(player_id="alice", client_message_id="ordinary", text="普通群聊继续安排回应"),
    )
    assert application.planner.plan()
    with application.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM conversation_tasks WHERE conversation_id='conversation'"
            ).fetchone()[0]
            > 0
        )


def test_game_and_conversation_rollback_together_on_real_membership_failure(client):
    application = client.app.state.application
    created = create(application)
    joined = join(application, created)
    # 使用真实会话业务制造缺失成员，验证游戏离开成功后会话失败时整体回滚。
    with application.database.transaction() as connection:
        application.conversations.leave_in(
            connection, "community", created.conversation.conversation_id, BOB
        )
    game = summary(application, created.game_id)
    with application.database.read() as connection:
        events_before = connection.execute("SELECT COUNT(*) FROM realtime_events").fetchone()[0]
        receipts_before = connection.execute(
            "SELECT COUNT(*) FROM game_operation_receipts"
        ).fetchone()[0]
    command = LeaveGameCommand(
        game_id=created.game_id,
        request_id="broken-leave",
        expected_state_version=2,
        participation_id=joined.game_receipt.result.participation.participation_id,
    )
    with pytest.raises(NotFoundError):
        application.game_participation.leave_game(BOB, command)
    assert summary(application, created.game_id) == game
    assert (
        application.game_participation.read_operation(BOB, created.game_id, "broken-leave") is None
    )
    with application.database.read() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM realtime_events").fetchone()[0]
            == events_before
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM game_operation_receipts").fetchone()[0]
            == receipts_before
        )
    with pytest.raises(ConflictError, match="disagree"):
        application.game_participation.start_game(
            ALICE,
            StartGameCommand(
                game_id=created.game_id, request_id="broken-start", expected_state_version=2
            ),
        )
    with application.database.transaction() as connection:
        application.conversations.join_in(
            connection, "community", created.conversation.conversation_id, BOB
        )
    assert (
        application.game_participation.leave_game(BOB, command).game_receipt.state_version_after
        == 3
    )


def test_request_scope_and_identity_are_checked_before_returning_old_results(client):
    application = client.app.state.application
    created = create(application)
    application.communities.create("另一个社群", "UTC", community_id="other", player_id="alice")
    with pytest.raises(IdempotencyConflict):
        application.game_participation.create_game(
            ALICE,
            CreateGameSessionCommand(
                community_id="other", game=GomokuCreateGameCommand(request_id="create")
            ),
        )
    with pytest.raises(IdempotencyConflict):
        application.game_participation.end_activity(
            ALICE,
            EndGameActivityCommand(
                game_id=created.game_id,
                request_id="create",
                expected_state_version=1,
                expected_conversation_version=1,
            ),
        )
    application.communities.register_player("社群外玩家", player_id="outside")
    with pytest.raises(NotFoundError):
        application.game_participation.read_operation(
            ActorRef("player", "outside"), created.game_id, "create"
        )
    with pytest.raises(GameError):
        application.game_participation.read_operation(
            ActorRef("character", "first"), created.game_id, "create"
        )


def test_parallel_create_retries_return_one_game_and_one_conversation(client):
    application = client.app.state.application
    with ThreadPoolExecutor(max_workers=3) as pool:
        results = list(pool.map(lambda _: create(application), range(3)))
    assert results == [results[0]] * 3
    with application.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM community_games").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM game_session_operations").fetchone()[0] == 1
        assert (
            connection.execute("SELECT COUNT(*) FROM conversations WHERE kind='game'").fetchone()[0]
            == 1
        )


def test_noncreator_and_old_versions_cannot_end_or_cancel_game(client):
    application = client.app.state.application
    created = create(application)
    joined = join(application, created)
    command = EndGameActivityCommand(
        game_id=created.game_id,
        request_id="end",
        expected_state_version=2,
        expected_conversation_version=1,
    )
    with pytest.raises(GameError) as failure:
        application.game_participation.end_activity(BOB, command)
    assert failure.value.code == "operation_forbidden"
    with pytest.raises(GameError) as failure:
        application.game_participation.cancel_game(
            BOB,
            CancelGameCommand(
                game_id=created.game_id,
                request_id="cancel",
                expected_state_version=2,
                reason="no_permission",
            ),
        )
    assert failure.value.code == "operation_forbidden"
    with pytest.raises(ConflictError):
        application.game_participation.end_activity(
            ALICE, command.model_copy(update={"expected_conversation_version": 999})
        )
    with pytest.raises(GameError) as failure:
        application.game_participation.end_activity(
            ALICE, command.model_copy(update={"expected_state_version": 1})
        )
    assert failure.value.code == "state_version_conflict"
    assert summary(application, created.game_id).state_version == 2
    ended, _ = end(application, created)
    assert (
        application.game_participation.join_game(
            BOB,
            JoinGameSessionCommand(
                game_id=created.game_id,
                request_id="join",
                expected_state_version=1,
                seat_id="white",
                participant=BOB,
            ),
        )
        == joined
    )
    assert ended.conversation.status == "archived"


def test_pause_and_restart_preserve_seats_chat_and_original_combined_receipts(client):
    application = client.app.state.application
    created = create(application)
    joined = join(application, created)
    application.communities.update("community", expected_version=1, status="paused")
    application.game_participation.start_game(
        ALICE,
        StartGameCommand(game_id=created.game_id, request_id="start", expected_state_version=2),
    )
    message(application, created, "暂停期间真人仍可发言")
    settings = client.app.state.settings
    with TestClient(create_app(settings)) as restarted:
        other = restarted.app.state.application
        assert summary(other, created.game_id).state_version == 3
        assert other.game_participation.read_operation(ALICE, created.game_id, "create") == created
        assert other.game_participation.read_operation(BOB, created.game_id, "join") == joined
        play(other, created.game_id, ALICE, 7, 7)


def test_version_21_upgrade_preserves_all_existing_rows_and_adds_game_chat(tmp_path):
    scripts = tmp_path / "version21"
    scripts.mkdir()
    for item in files("echo_commons.infrastructure.database.sql").iterdir():
        if item.name.endswith(".sql") and int(item.name.split("_", 1)[0]) <= 21:
            shutil.copyfile(str(item), scripts / item.name)
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"model_secrets_path": str(tmp_path / "absent-credentials.toml")}
    )
    database = load_history(19, settings.database_path)
    assert initialize(database, sql_directory=scripts) == 21
    from echo_commons.app.composition import assemble

    with database.read() as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name!='schema_migrations'"
            )
        ]
        tables = [
            table for table in tables if table not in {"social_candidates", "social_triggers"}
        ]
        columns = {
            table: ",".join(
                f'"{row[1]}"'
                for row in connection.execute(f'PRAGMA table_info("{table}")')
                if row[1] not in {"parent_turn_id", "depth", "root_turn_id"}
            )
            for table in tables
        }
        before = {
            table: [
                tuple(row) for row in connection.execute(f'SELECT {columns[table]} FROM "{table}"')
            ]
            for table in tables
        }
    assert initialize(database) == initialize(database) == 26
    with database.read() as connection:
        assert {
            table: [
                tuple(row) for row in connection.execute(f'SELECT {columns[table]} FROM "{table}"')
            ]
            for table in tables
        } == before
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    assert create(assemble(settings)).conversation.kind == "game"
