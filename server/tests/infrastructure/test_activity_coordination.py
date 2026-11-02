import asyncio
import json
from concurrent.futures import ThreadPoolExecutor
from functools import partial

import pytest
from echo_games.public import AeroplaneCreateGameCommand
from fastapi.testclient import TestClient
from support.activities import activity_game, message
from support.activity_actions import task_row
from support.application import settings_for
from support.games import create, move, operation
from support.http import create_group
from support.migrations import load_history

from echo_commons.agents.contracts.activity import ACTIVITY_REPLY_CONTRACT, ActivityReplyProposal
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.execution.lease import LeaseLostError
from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.activities.gameplay.contracts import GameplayAnalysisError
from echo_commons.modules.activities.tasks.prompt import decision_questions
from echo_commons.modules.communities.contracts import CreateGameSessionCommand
from echo_commons.modules.conversations.tasks.memory import ContextBudgetExceeded
from echo_commons.shared.actors import ActorRef


@pytest.fixture
def client(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(update={"retry_backoff_seconds": 0})
    with TestClient(create_app(settings)) as client:
        client.app.state.application.intake.quiet_seconds = 0
        yield client


def waiting_game(client):
    create_group(client, memory_mode="simple")
    created, _ = create(client)
    game = created["game_id"]
    operation(
        client,
        game,
        "participants",
        seat_id="white",
        participant={"kind": "character", "character_id": "first"},
    )
    return game


def plan_reply(client, game, text="等会儿你先别催我，我得研究一下~"):
    app = client.app.state.application
    sent = message(client, game, text)
    (turn,) = app.planner.plan()
    (identity,) = app.activity_coordinator.scan()
    return identity, turn, sent


def frozen(client, identity):
    app = client.app.state.application
    row = task_row(app, identity)
    return client.portal.call(
        partial(
            getattr(app.activity_context, f"prepare_{row['purpose']}"),
            row["community_id"],
            row["character_id"],
            row["game_id"],
            input_id=row["input_id"],
            participation_id=row["participation_id"],
        )
    )


def test_game_collection_selects_activity_and_keeps_exact_source(client):
    game = waiting_game(client)
    identity, turn, sent = plan_reply(client, game)
    app = client.app.state.application
    row = task_row(app, identity)
    assert row["purpose"] == "reply" and row["opportunity_id"] is None
    with app.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM input_batches").fetchone()[0] == 1
        source = connection.execute("SELECT * FROM activity_task_sources").fetchone()
        assert source["social_turn_id"] == turn and source["task_id"] == identity
        assert source["observation_max_sequence"] == sent.sequence
        assert source["status"] == "attached"
        chain = app.planner.social.active_chain(connection, row["conversation_id"])
        assert (chain.task_count, chain.message_count) == (1, 0)
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_reply_freezes_before_memory_and_has_no_action_capability(client):
    game = waiting_game(client)
    identity, _, sent = plan_reply(client, game)
    snapshot = frozen(client, identity)
    assert snapshot.kind == "reply" and snapshot.material.game.view is None
    assert snapshot.action_space.output_contracts[0] == ACTIVITY_REPLY_CONTRACT
    assert snapshot.material.conversation.perspective.trigger_message_ids == (sent.message_id,)
    assert snapshot.material.working_memory.intents == ()
    assert "action" not in ActivityReplyProposal.model_fields
    assert set(decision_questions(snapshot)) == {"participation"}
    later = message(client, game, "我刚才开玩笑的啦。")
    assert frozen(client, identity) == snapshot
    assert later.message_id not in snapshot.model_dump_json()
    app = client.app.state.application
    with app.database.read() as connection:
        assert (
            connection.execute("SELECT status FROM activity_task_sources").fetchone()[0] == "frozen"
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM activity_observation_progress").fetchone()[0]
            == 0
        )


def test_unfrozen_reply_merges_real_opportunity(client):
    game = waiting_game(client)
    identity, _, sent = plan_reply(client, game)
    operation(client, game, "start")
    move(client, game, "alice", 7, 7)
    app = client.app.state.application
    assert app.activity_coordinator.scan() == (identity,)
    assert task_row(app, identity)["purpose"] == "turn"
    snapshot = frozen(client, identity)
    assert snapshot.kind == "turn" and snapshot.opportunity.legal_actions
    assert snapshot.material.conversation.perspective.trigger_message_ids == (sent.message_id,)
    with app.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM activity_tasks").fetchone()[0] == 1


def test_frozen_reply_survives_board_change_and_queues_new_opportunity(client):
    game = waiting_game(client)
    identity, _, _ = plan_reply(client, game)
    snapshot = frozen(client, identity)
    operation(client, game, "start")
    move(client, game, "alice", 7, 7)
    app = client.app.state.application
    assert app.activity_coordinator.scan() == ()
    row = task_row(app, identity)
    assert row["purpose"] == "reply"
    with app.database.read() as connection:
        assert app.activity_execution.review.source_code(connection, row) is None
        assert connection.execute("SELECT COUNT(*) FROM activity_tasks").fetchone()[0] == 1
    assert frozen(client, identity) == snapshot


@pytest.mark.parametrize(
    ("blocked_by", "completion_path"),
    [
        (None, "lifecycle"),
        ("community", "lifecycle"),
        ("character", "lifecycle"),
        ("character", "recovery"),
    ],
)
def test_resignation_cancels_merged_action_and_preserves_valid_chat_as_postgame_reply(
    client, blocked_by, completion_path
):
    game = activity_game(client)
    app = client.app.state.application
    identity, turn, sent = plan_reply(client, game, "这局结束后想听听你的感想。")
    before = frozen(client, identity)
    lease = client.portal.call(app.activity_queue.claim, "interrupted-action", utc_now())
    assert task_row(app, identity)["purpose"] == "turn"
    with app.database.read() as connection:
        participation_id = app.game_queries.participant_context(
            connection, "community", ActorRef("player", "alice"), game
        ).access.participation_id
    if blocked_by == "community":
        app.communities.update("community", expected_version=1, status="paused")
    elif blocked_by == "character":
        app.character_state.set_availability("community", "first", "busy", expected_version=0)
    operation(client, game, "resign", participation_id=participation_id)
    if completion_path == "recovery":
        with app.database.read() as connection:
            code = app.activity_execution.review.source_code(
                connection, app.activity_queue.repository.get(connection, identity)
            )
        assert code == "opportunity_replaced"
        client.portal.call(
            app.activity_queue.apply_recovery,
            lease,
            utc_now(),
            app.activity_queue.recovery.source(code),
        )
    if blocked_by:
        assert app.activity_coordinator.scan() == ()
        with app.database.read() as connection:
            source = connection.execute("SELECT * FROM activity_task_sources").fetchone()
            assert source["status"] == "queued" and source["task_id"] is None
            assert app.planner.social.by_id(connection, turn).status == "running"
        assert client.portal.call(app.activity_queue.claim, "blocked", utc_now()) is None
        if blocked_by == "community":
            app.communities.update("community", expected_version=2, status="active")
        else:
            app.character_state.set_availability(
                "community", "first", "available", expected_version=1
            )
    (reply_id,) = app.activity_coordinator.scan()
    assert reply_id != identity and task_row(app, identity)["status"] == "cancelled"
    assert task_row(app, reply_id)["purpose"] == "reply"
    assert not client.portal.call(app.activity_queue.renew, lease, utc_now())
    reply = frozen(client, reply_id)
    assert reply.material.game.status == "finished"
    assert reply.material.conversation.perspective.trigger_message_ids == (sent.message_id,)
    assert reply.material.responses[0].source_id == before.material.responses[0].source_id
    with app.database.read() as connection:
        assert (
            connection.execute(
                "SELECT status FROM social_turns WHERE social_turn_id=?", (turn,)
            ).fetchone()[0]
            == "running"
        )
        assert connection.execute("SELECT COUNT(*) FROM activity_results").fetchone()[0] == 0


def test_game_turn_does_not_wait_for_chat_window_or_spend_chat_budget(client):
    game = activity_game(client)
    app = client.app.state.application
    app.intake.quiet_seconds = 60
    sent = message(client, game, "你的回合~")
    assert not app.planner.plan()
    (identity,) = app.activity_coordinator.scan()
    assert task_row(app, identity)["purpose"] == "turn"
    with app.database.read() as connection:
        chain = app.planner.social.active_chain(connection, sent.conversation_id)
        assert chain is None or (chain.task_count, chain.message_count) == (0, 0)
        assert connection.execute("SELECT COUNT(*) FROM activity_task_sources").fetchone()[0] == 0


def test_source_arriving_after_preparation_waits_for_next_judgment(client):
    game = activity_game(client)
    app = client.app.state.application
    (identity,) = app.activity_coordinator.scan()
    before = frozen(client, identity)
    sent = message(client, game, "刚才想起来，输了讲笑话如何？")
    app.planner.plan()
    assert app.activity_coordinator.scan() == (identity,)
    with app.database.read() as connection:
        source = connection.execute("SELECT * FROM activity_task_sources").fetchone()
        assert source["status"] == "queued" and source["task_id"] is None
    detail = client.get(
        f"/internal/communities/community/characters/first/activity-tasks/{source['source_id']}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["task"]["status"] == "queued"
    assert detail.json()["working_memory"] is None
    assert (
        client.get(
            f"/internal/communities/community/characters/second/activity-tasks/{source['source_id']}"
        ).status_code
        == 404
    )
    assert sent.message_id not in before.model_dump_json()


def test_waiting_initiation_uses_activity_without_fabricated_message(client):
    game = waiting_game(client)
    app = client.app.state.application
    with app.database.read() as connection:
        conversation = connection.execute(
            "SELECT conversation_id FROM community_games WHERE game_id=?", (game,)
        ).fetchone()[0]
    request = partial(
        app.conversation_initiations.request,
        "community",
        conversation,
        "first",
        "等待开局时想打声招呼。",
        request_id="opening",
    )
    source = request()
    assert request() == source
    (identity,) = app.activity_coordinator.scan()
    snapshot = frozen(client, identity)
    assert identity != source and snapshot.kind == "reply"
    assert "等待开局时想打声招呼" in snapshot.material.conversation.perspective.situation
    assert snapshot.material.conversation.perspective.trigger_message_ids == ()
    with app.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 0
        assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 0
    response = client.get(
        f"/internal/communities/community/characters/first/activity-tasks/{source}"
    )
    assert response.status_code == 200, response.text
    assert response.json()["task"]["purpose"] == "reply"


@pytest.mark.parametrize("change", ["cancel", "archive", "leave"])
def test_reply_lifecycle_cancels_original_sources(client, change):
    game = waiting_game(client)
    identity, turn, sent = plan_reply(client, game)
    frozen(client, identity)
    app = client.app.state.application
    lease = client.portal.call(app.activity_queue.claim, "lifecycle", utc_now())
    if change == "cancel":
        operation(client, game, "cancel", reason="player_request")
    elif change == "archive":
        with app.database.read() as connection:
            version = connection.execute(
                "SELECT state_version FROM conversations WHERE conversation_id=?",
                (sent.conversation_id,),
            ).fetchone()[0]
        operation(client, game, "end", expected_conversation_version=version)
    else:
        with app.database.read() as connection:
            participation = app.game_queries.participant_context(
                connection, "community", ActorRef("character", "first"), game
            ).access.participation_id
        operation(client, game, "leave", participation_id=participation)
    app.activity_coordinator.scan()
    assert task_row(app, identity)["status"] == "cancelled"
    with pytest.raises(LeaseLostError):
        client.portal.call(app.activity_execution.execute, lease)
    with app.database.read() as connection:
        assert (
            connection.execute("SELECT status FROM activity_task_sources").fetchone()[0]
            == "cancelled"
        )
        assert app.planner.social.by_id(connection, turn).status in ("completed", "cancelled")


def test_paused_reply_resumes_with_original_input_and_cleanup_covers_sources(client):
    game = waiting_game(client)
    identity, _, _ = plan_reply(client, game)
    before = frozen(client, identity)
    app = client.app.state.application
    app.communities.update("community", expected_version=1, status="paused")
    assert task_row(app, identity)["status"] == "suspended"
    app.communities.update("community", expected_version=2, status="active")
    app.activity_coordinator.scan()
    assert task_row(app, identity)["status"] == "pending"
    assert frozen(client, identity) == before
    app.communities.update("community", expected_version=3, status="paused")
    response = client.post(
        "/internal/maintenance/cleanup", json={"community_ids": ["community"], "dry_run": False}
    )
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["activity_task_sources"] == 1
    with app.database.read() as connection:
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.model
def test_real_local_reply_saves_decision_without_inventing_understanding(
    tmp_path, record_testsuite_property
):
    from test_activity_models import decision_settings

    with TestClient(create_app(decision_settings(tmp_path))) as client:
        app = client.app.state.application
        app.intake.quiet_seconds = 0
        game = waiting_game(client)
        identity, turn, sent = plan_reply(client, game, "我去倒杯水，先不用回复我，回来再开始。")
        lease = client.portal.call(app.activity_queue.claim, "local-reply", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        assert artifact["mode"] == "decision"
        assert set(artifact["decision_request"]["questions"]) == {"participation"}
        assert artifact["run"]["output"]["contract"]["kind"] == "activity_reply_selection"
        assert client.portal.call(app.activity_execution.execute, lease) == artifact
        result = app.activity_commit.commit(lease, artifact)
        assert result["receipt"] is None
        with app.database.read() as connection:
            input_id = app.activity_queue.repository.get(connection, identity)["input_id"]
            input_row = app.activity_context.inputs.get(connection, "community", "first", input_id)
            assert input_row["understanding_json"] is None
            assert connection.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
            chain = app.planner.social.chain(
                connection, app.planner.social.by_id(connection, turn).chain_id
            )
            assert (chain.task_count, chain.message_count) == (1, 0)
        assert (
            sent.message_id
            in app.activity_context.pending_sources("community", "first", game)["message_ids"]
        )
        record_testsuite_property("local_reply", json.dumps(artifact, ensure_ascii=False))


@pytest.mark.model
def test_real_local_reply_delegates_new_intent_to_ordinary_model(
    tmp_path, record_testsuite_property
):
    from test_activity_models import decision_settings

    with TestClient(create_app(decision_settings(tmp_path))) as client:
        app = client.app.state.application
        app.intake.quiet_seconds = 0
        game = waiting_game(client)
        operation(client, game, "start")
        identity, _, sent = plan_reply(
            client,
            game,
            "我想跟你约定这盘先练习封堵，每次我忘记看对手的威胁你就提醒我，"
            "不过你可以有自己的想法，想换个练法也说说？",
        )
        assert task_row(app, identity)["purpose"] == "reply"
        lease = client.portal.call(app.activity_queue.claim, "local-understanding", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        assert artifact["mode"] == "decision_then_ordinary"
        assert artifact["decision_response"]["answers"]["intent_update"]["choice"] == "understand"
        assert artifact["run"]["output"]["contract"]["kind"] == "activity_reply"
        assert "action" not in artifact["run"]["output"]["payload"]
        result = app.activity_commit.commit(lease, artifact)
        assert result["receipt"] is None
        with app.database.read() as connection:
            input_id = app.activity_queue.repository.get(connection, identity)["input_id"]
            row = app.activity_context.inputs.get(connection, "community", "first", input_id)
            understood = json.loads(row["understanding_json"])
            assert understood["messages"][0]["message_id"] == sent.message_id
            assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        record_testsuite_property("local_understanding", json.dumps(artifact, ensure_ascii=False))


def test_multiple_roles_use_mentions_and_failure_moves_to_next_role_without_analyzer(client):
    create_group(client, memory_mode="simple")
    app = client.app.state.application
    created = app.game_participation.create_game(
        ActorRef("player", "alice"),
        CreateGameSessionCommand(
            community_id="community", game=AeroplaneCreateGameCommand(request_id="aeroplane")
        ),
    )
    game = created.game_id
    for seat, character in [("yellow", "first"), ("blue", "second")]:
        operation(
            client,
            game,
            "participants",
            seat_id=seat,
            participant={"kind": "character", "character_id": character},
        )
    message(client, game, "你们准备好了叫我~", mentions=(ActorRef("character", "second"),))
    app.planner.plan()
    (identity,) = app.activity_coordinator.scan()
    assert task_row(app, identity)["character_id"] == "second"
    app.activity_context.policy = app.activity_context.policy.model_copy(
        update={"input_max_chars": 1}
    )
    lease = client.portal.call(app.activity_queue.claim, "budget-failure", utc_now())
    with pytest.raises(ContextBudgetExceeded) as failure:
        client.portal.call(app.activity_execution.execute, lease)
    client.portal.call(
        app.activity_queue.apply_recovery,
        lease,
        utc_now(),
        app.activity_queue.recovery.classify(failure.value),
    )
    assert task_row(app, identity)["status"] == "failed"
    app.planner.plan()
    (next_id,) = app.activity_coordinator.scan()
    assert task_row(app, next_id)["character_id"] == "first"
    assert task_row(app, next_id)["purpose"] == "reply"
    with app.database.read() as connection:
        statuses = [
            r[0]
            for r in connection.execute(
                "SELECT status FROM activity_task_sources ORDER BY created_at_utc"
            )
        ]
        assert statuses == ["failed", "attached"]
        assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 0


def test_version_31_upgrade_preserves_real_tasks_receipts_thoughts_and_pending_requests(tmp_path):
    database = load_history(31, tmp_path / "history.sqlite3")
    with database.read() as connection:
        tables = [
            r[0]
            for r in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'memory_search_fts_%' AND name!='schema_migrations'"
            )
        ]
        before = {
            table: [dict(r) for r in connection.execute(f'SELECT * FROM "{table}"')]
            for table in tables
        }
        assert before["activity_results"][0]["receipt_json"]
        assert before["thoughts"][0]["activity_result_id"]
        assert before["conversation_tasks"][0]["status"] == "pending"
    assert initialize(database) == initialize(database) == 32
    with database.read() as connection:
        for table, rows in before.items():
            after = [dict(r) for r in connection.execute(f'SELECT * FROM "{table}"')]
            if table == "activity_tasks":
                assert all(r.pop("purpose") == "turn" for r in after)
            assert after == rows, table
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.model
def test_real_legacy_game_request_finishes_in_original_path_and_new_request_uses_activity(tmp_path):
    database = load_history(31, tmp_path / "legacy.sqlite3")
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"database_path": str(database.path)}
    )
    with TestClient(create_app(settings)) as client:
        app = client.app.state.application
        with database.read() as connection:
            original = dict(connection.execute("SELECT * FROM conversation_initiations").fetchone())
            old_task = connection.execute("SELECT task_id FROM conversation_tasks").fetchone()[0]
        assert (
            app.conversation_initiations.request(
                original["community_id"],
                original["conversation_id"],
                original["character_id"],
                original["situation"],
                request_id=original["request_id"],
            )
            == old_task
        )
        lease = client.portal.call(app.queue.claim, "legacy-conversation", utc_now())
        assert lease.task_id == old_task and lease.task_kind == "conversation_reply"
        client.portal.call(app.handler.execute, lease)
        with database.read() as connection:
            assert (
                connection.execute(
                    "SELECT status FROM conversation_tasks WHERE task_id=?", (old_task,)
                ).fetchone()[0]
                == "completed"
            )
            assert connection.execute("SELECT COUNT(*) FROM activity_results").fetchone()[0] == 1
            assert (
                connection.execute("SELECT COUNT(*) FROM conversation_results").fetchone()[0] == 1
            )
        source = app.conversation_initiations.request(
            "community",
            original["conversation_id"],
            "first",
            "想补充一句刚才的玩笑。",
            request_id="new-activity-request",
        )
        (identity,) = app.activity_coordinator.scan()
        assert task_row(app, identity)["purpose"] == "reply"
        with database.read() as connection:
            assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 1
            assert (
                connection.execute(
                    "SELECT task_id FROM activity_task_sources WHERE source_id=?", (source,)
                ).fetchone()[0]
                == identity
            )


@pytest.mark.model
def test_real_local_pending_expression_is_visible_and_does_not_block_new_sources(tmp_path):
    from test_activity_models import decision_settings

    with TestClient(create_app(decision_settings(tmp_path))) as client:
        app = client.app.state.application
        app.intake.quiet_seconds = 0
        game = waiting_game(client)
        identity, _, first = plan_reply(client, game, "嗨，小槿，开局前跟我打声招呼吧~")
        lease = client.portal.call(app.activity_queue.claim, "local-expression", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        assert artifact["mode"] == "decision"
        assert artifact["decision_response"]["answers"]["participation"]["choice"] == "participate"
        result = app.activity_commit.commit(lease, artifact)
        with app.database.read() as connection:
            saved = app.activity_commit.results.for_task(connection, identity)
            assert saved["expression_status"] == "pending_generation"
            assert saved["expression_json"] is None
            assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        app.planner.plan()
        assert not app.activity_coordinator.scan()
        second = message(client, game, "我回来啦，已经准备好了！")
        app.planner.plan()
        (next_id,) = app.activity_coordinator.scan()
        assert next_id != identity
        snapshot = frozen(client, next_id)
        old = next(r for r in snapshot.material.responses if r.result_id == result["result_id"])
        assert not old.current and old.status == "pending_expression"
        assert old.message_ids == (first.message_id,)
        assert next(r for r in snapshot.material.responses if r.current).message_ids == (
            second.message_id,
        )


def test_failed_opportunity_waits_for_new_source_before_scheduling_again(client):
    game = activity_game(client)
    app = client.app.state.application
    identity, _, _ = plan_reply(client, game, "这步要认真想想哦。")
    original = app.rapfi.settings
    app.rapfi.settings = original.model_copy(update={"timeout_seconds": 0.000001})
    for attempt in range(1, app.activity_queue.policy.max_attempts + 1):
        lease = client.portal.call(app.activity_queue.claim, "engine-failure", utc_now())
        assert lease.attempt == attempt
        with pytest.raises(GameplayAnalysisError) as failure:
            client.portal.call(app.activity_execution.execute, lease)
        client.portal.call(
            app.activity_queue.apply_recovery,
            lease,
            utc_now(),
            app.activity_queue.recovery.classify(failure.value),
        )
    assert task_row(app, identity)["status"] == "failed"
    assert not app.activity_coordinator.scan()
    app.planner.plan()
    message(client, game, "换个想法，现在你觉得呢？")
    app.planner.plan()
    (new_id,) = app.activity_coordinator.scan()
    assert new_id != identity
    assert task_row(app, new_id)["opportunity_id"] == task_row(app, identity)["opportunity_id"]
    app.rapfi.settings = original
    assert frozen(client, new_id).opportunity.legal_actions


def test_parallel_scanners_and_workers_keep_one_task_and_partial_preparation_is_frozen(client):
    game = activity_game(client)
    app = client.app.state.application
    with ThreadPoolExecutor(max_workers=2) as workers:
        scheduled = list(workers.map(lambda _: app.activity_coordinator.scan(), range(2)))
    assert scheduled[0] == scheduled[1] and len(scheduled[0]) == 1
    identity = scheduled[0][0]

    async def claim_together():
        return await asyncio.gather(
            app.activity_queue.claim("worker-one", utc_now()),
            app.activity_queue.claim("worker-two", utc_now()),
        )

    leases = [lease for lease in client.portal.call(claim_together) if lease]
    assert len(leases) == 1
    lease = leases[0]
    original = app.rapfi.settings
    app.rapfi.settings = original.model_copy(update={"timeout_seconds": 0.000001})
    with pytest.raises(GameplayAnalysisError) as failure:
        client.portal.call(app.activity_execution.execute, lease)
    client.portal.call(
        app.activity_queue.apply_recovery,
        lease,
        utc_now(),
        app.activity_queue.recovery.classify(failure.value),
    )
    app.rapfi.settings = original
    later = message(client, game, "刚想起来，我想换个练法。")
    app.planner.plan()
    assert app.activity_coordinator.scan() == (identity,)
    with app.database.read() as connection:
        row = app.activity_queue.repository.get(connection, identity)
        saved = app.activity_context.inputs.get(connection, "community", "first", row["input_id"])
        assert saved["preparation_json"] and saved["snapshot_json"] is None
        assert later.message_id not in saved["preparation_json"]
        source = connection.execute("SELECT * FROM activity_task_sources").fetchone()
        assert source["status"] == "queued" and source["task_id"] is None
        assert connection.execute("SELECT COUNT(*) FROM activity_tasks").fetchone()[0] == 1


@pytest.mark.model
def test_real_postgame_reply_has_no_current_intent_or_action(client):
    game = waiting_game(client)
    operation(client, game, "start")
    app = client.app.state.application
    with app.database.read() as connection:
        participation_id = app.game_queries.participant_context(
            connection, "community", ActorRef("player", "alice"), game
        ).access.participation_id
    operation(client, game, "resign", participation_id=participation_id)
    identity, _, sent = plan_reply(client, game, "这盘是我输了，下次有机会再比~")
    snapshot = frozen(client, identity)
    assert snapshot.material.game.status == "finished"
    assert not snapshot.material.working_memory.intents
    assert set(decision_questions(snapshot)) == {"participation"}
    lease = client.portal.call(app.activity_queue.claim, "postgame", utc_now())
    artifact = client.portal.call(app.activity_execution.execute, lease)
    payload = artifact["run"]["output"]["payload"]
    assert not payload["intents"] and "action" not in payload
    assert payload["understanding"]["messages"][0]["message_id"] == sent.message_id
    assert app.activity_commit.commit(lease, artifact)["receipt"] is None
    with app.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM activity_working_memory").fetchone()[0] == 0


@pytest.mark.model
def test_real_reply_preserves_frozen_sources_then_executes_waiting_opportunity(
    client, record_testsuite_property
):
    game = waiting_game(client)
    identity, turn, sent = plan_reply(client, game, "嘿嘿，等会儿输了的人要讲个笑话~")
    original = frozen(client, identity)
    operation(client, game, "start")
    move(client, game, "alice", 7, 7)
    app = client.app.state.application
    lease = client.portal.call(app.activity_queue.claim, "real-reply", utc_now())
    assert lease.task_kind == "activity_reply"
    artifact = client.portal.call(app.activity_execution.execute, lease)
    assert artifact["invocation"]["identity"]["purpose"] == "activity_reply"
    payload = artifact["run"]["output"]["payload"]
    assert "action" not in payload and not payload["intents"]
    assert payload["understanding"]["messages"][0]["message_id"] == sent.message_id
    with app.database.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER reject_reply_result BEFORE INSERT ON activity_results "
            "BEGIN SELECT RAISE(ABORT,'real reply persistence failure'); END"
        )
    with pytest.raises(StorageError):
        app.activity_commit.commit(lease, artifact)
    with app.database.transaction() as connection:
        connection.execute("DROP TRIGGER reject_reply_result")
        assert (
            connection.execute("SELECT status FROM activity_task_sources").fetchone()[0] == "frozen"
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM activity_observation_progress").fetchone()[0]
            == 0
        )
    result = app.activity_commit.commit(lease, artifact)
    assert result["receipt"] is None
    assert app.activity_commit.commit(lease, artifact) == result
    with app.database.read() as connection:
        chain = app.planner.social.chain(
            connection, app.planner.social.by_id(connection, turn).chain_id
        )
        assert (chain.task_count, chain.message_count) == (1, 0)
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM thoughts WHERE activity_result_id=?", (result["result_id"],)
            ).fetchone()[0]
            <= 1
        )
    assert app.activity_context.restore("community", "first", original.snapshot_id) == original
    (action_id,) = app.activity_coordinator.scan()
    assert action_id != identity and task_row(app, action_id)["purpose"] == "turn"
    worker = app.supervisor.workers["activities-0"]
    for _ in range(app.activity_queue.policy.max_attempts):
        assert client.portal.call(worker.run_once)
        state = task_row(app, action_id)["status"]
        if state == "completed":
            break
        assert state == "retry_wait", task_row(app, action_id)
    assert task_row(app, action_id)["status"] == "completed"
    with app.database.read() as connection:
        assert app.activity_commit.results.for_task(connection, action_id)["receipt_json"]
    record_testsuite_property("reply_artifact", json.dumps(artifact, ensure_ascii=False))
