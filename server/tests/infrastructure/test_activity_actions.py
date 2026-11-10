import asyncio
import json
import time
from contextlib import AsyncExitStack
from functools import partial
from pathlib import Path

import pytest
from echo_games.public import CancelGameCommand
from fastapi.testclient import TestClient
from support.activities import activity_game, message, prepare
from support.activity_actions import (
    ALICE,
    CHARACTER,
    create_character_black,
    fill_draw,
    play_in,
    task_row,
)
from support.application import settings_for
from support.http import create_group

from echo_commons.agents.contracts.activity import IntentProposal
from echo_commons.agents.contracts.invocation import InvocationPurpose
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.execution.lease import LeaseLostError
from echo_commons.modules.activities.gameplay.contracts import GameplayAnalysisError


@pytest.fixture
def client(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(update={"retry_backoff_seconds": 0})
    with TestClient(create_app(settings)) as client:
        yield client


def test_single_legal_action_uses_real_board_without_model_and_is_idempotent(client):
    create_group(client, memory_mode="simple")
    app = client.app.state.application
    game = create_character_black(app)
    fill_draw(app, game, 224)
    original = message(client, game, "这一格可没得选了，下一局再比。")
    (task_id,) = app.activity_coordinator.scan()
    assert task_row(app, task_id)["mode"] == "automatic"
    assert app.activity_coordinator.scan() == (task_id,)
    lease = client.portal.call(app.activity_queue.claim, "automatic", utc_now())
    artifact = client.portal.call(app.activity_execution.execute, lease)
    assert artifact["run"] is None
    assert artifact["decision"]["input_id"] is None
    assert artifact["decision"]["thought"] is None
    assert artifact["decision"]["speech"]["kind"] == "silent"
    assert client.portal.call(app.activity_execution.execute, lease) == artifact
    receipt = app.activity_commit.commit(lease, artifact)
    assert app.activity_commit.commit(lease, artifact) == receipt
    with app.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM activity_results").fetchone()[0] == 1
        result = app.activity_commit.results.for_task(connection, task_id)
        assert json.loads(result["artifact_json"])["decision"] == artifact["decision"]
        assert result["expression_status"] == result["publication_status"] == "silent"
        assert (
            connection.execute("SELECT COUNT(*) FROM activity_expression_tasks").fetchone()[0] == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM activity_inputs").fetchone()[0] == 0
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM thoughts WHERE activity_result_id IS NOT NULL"
            ).fetchone()[0]
            == 0
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM activity_observation_progress").fetchone()[0]
            == 0
        )
    assert (
        original.message_id
        in app.activity_context.pending_sources("community", "first", game)["message_ids"]
    )
    assert not app.activity_coordinator.scan()
    assert task_row(app, task_id)["status"] == "completed"
    with app.database.read() as connection:
        assert (
            app.game_queries.participant_context(
                connection, "community", CHARACTER, game
            ).game.result.reason
            == "board_full"
        )
    detail = client.get(
        f"/internal/communities/community/characters/first/activity-tasks/{task_id}"
    )
    assert detail.status_code == 200, detail.text
    assert detail.json()["result"]["execution_mode"] == "automatic"
    assert detail.json()["result"]["publication_status"] == "silent"
    assert (
        client.get(
            f"/internal/communities/community/characters/second/activity-tasks/{task_id}"
        ).status_code
        == 404
    )


def test_pause_and_old_lease_cannot_execute_and_resume_preserves_task(client):
    game = activity_game(client)
    app = client.app.state.application
    (identity,) = app.activity_coordinator.scan()
    lease = client.portal.call(app.activity_queue.claim, "first", utc_now())
    app.communities.update("community", expected_version=1, status="paused")
    assert task_row(app, identity)["status"] == "suspended"
    assert not client.portal.call(app.activity_queue.renew, lease, utc_now())
    with pytest.raises(LeaseLostError):
        client.portal.call(app.activity_execution.execute, lease)
    app.communities.update("community", expected_version=2, status="active")
    assert app.activity_coordinator.scan() == (identity,)
    newer = client.portal.call(app.activity_queue.claim, "second", utc_now())
    assert newer.generation > lease.generation
    assert task_row(app, identity)["game_id"] == game
    with pytest.raises(LeaseLostError):
        app.activity_commit.commit(lease, {"mode": "automatic"})


def test_real_engine_failure_keeps_original_input_and_uses_bounded_recovery(client):
    game = activity_game(client)
    app = client.app.state.application
    original = message(client, game, "要不要试试边线呢？")
    (identity,) = app.activity_coordinator.scan()
    lease = client.portal.call(app.activity_queue.claim, "worker", utc_now())
    settings = app.rapfi.settings
    app.rapfi.settings = settings.model_copy(update={"timeout_seconds": 0.000001})
    with pytest.raises(GameplayAnalysisError) as failure:
        client.portal.call(app.activity_execution.execute, lease)
    client.portal.call(
        app.activity_queue.apply_recovery,
        lease,
        utc_now(),
        app.activity_queue.recovery.classify(failure.value),
    )
    assert task_row(app, identity)["status"] == "retry_wait"
    later = message(client, game, "刚才只是打趣。")
    app.rapfi.settings = settings
    frozen = client.portal.call(
        partial(
            app.activity_context.prepare_turn,
            "community",
            "first",
            game,
            input_id=task_row(app, identity)["input_id"],
            participation_id=task_row(app, identity)["participation_id"],
        )
    )
    assert frozen.material.conversation.perspective.trigger_message_ids == (original.message_id,)
    assert later.message_id not in frozen.model_dump_json()


def test_human_cancellation_clears_current_intent_even_while_paused(client):
    game = activity_game(client)
    app = client.app.state.application
    message(client, game, "约定围绕边线下棋。")
    frozen = prepare(client, game)
    app.activity_working_memory.replace(
        "community",
        "first",
        frozen.snapshot_id,
        expected_version=0,
        intents=(IntentProposal(content="考虑边线"),),
    )
    (identity,) = app.activity_coordinator.scan()
    app.communities.update("community", expected_version=1, status="paused")
    app.game_participation.cancel_game(
        ALICE,
        CancelGameCommand(
            game_id=game,
            request_id="cancel",
            reason="creator_cancelled",
            expected_state_version=frozen.material.game.state_version,
        ),
    )
    assert task_row(app, identity)["status"] == "cancelled"
    with app.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM activity_working_memory").fetchone()[0] == 0


def test_real_expiration_invalidates_old_lease(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={
            "lease_seconds": 0.12,
            "lease_safety_margin_seconds": 0,
            "lease_heartbeat_interval_seconds": 0.03,
            "retry_backoff_seconds": 0,
        }
    )
    with TestClient(create_app(settings)) as client:
        activity_game(client)
        app = client.app.state.application
        (identity,) = app.activity_coordinator.scan()
        lease = client.portal.call(app.activity_queue.claim, "expired", utc_now())
        time.sleep(0.15)
        assert client.portal.call(app.activity_queue.recover, utc_now()) == 1
        newer = client.portal.call(app.activity_queue.claim, "recovered", utc_now())
        assert newer.task_id == identity and newer.generation > lease.generation
        assert not client.portal.call(app.activity_queue.renew, lease, utc_now())


def test_replaced_opportunity_cancels_old_task_and_preserves_unread_chat(client):
    game = activity_game(client)
    source = message(client, game, "等等，我刚才想到一件事。")
    app = client.app.state.application
    (identity,) = app.activity_coordinator.scan()
    lease = client.portal.call(app.activity_queue.claim, "superseded", utc_now())
    with app.database.transaction() as connection:
        context = app.game_queries.participant_context(connection, "community", CHARACTER, game)
        view = app.games.read_view(connection, context.access)
        play_in(app, connection, game, CHARACTER, view.opportunities[0].legal_actions[0])
    client.portal.call(app.activity_queue.recover, utc_now())
    assert task_row(app, identity)["status"] == "cancelled"
    with pytest.raises(LeaseLostError):
        app.activity_commit.commit(lease, {"mode": "automatic"})
    assert (
        source.message_id
        in app.activity_context.pending_sources("community", "first", game)["message_ids"]
    )
    with app.database.transaction() as connection:
        context = app.game_queries.participant_context(connection, "community", ALICE, game)
        view = app.games.read_view(connection, context.access)
        play_in(app, connection, game, ALICE, view.opportunities[0].legal_actions[0])
    (new_identity,) = app.activity_coordinator.scan()
    assert new_identity != identity


def test_unreachable_local_service_uses_bounded_recovery_without_ordinary_fallback(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    target = tmp_path / "unreachable.toml"
    target.write_text(
        Path(settings.model_registry_path)
        .read_text(encoding="utf-8")
        .replace("[decision]\nenabled = false", "[decision]\nenabled = true")
        .replace("http://127.0.0.1:8090", "http://127.0.0.1:1"),
        encoding="utf-8",
    )
    settings = settings.model_copy(
        update={"model_registry_path": str(target), "retry_backoff_seconds": 0}
    )
    with TestClient(create_app(settings)) as client:
        game = activity_game(client)
        source = message(client, game, "我们继续下棋吧。")
        app = client.app.state.application
        (identity,) = app.activity_coordinator.scan()
        for _ in range(settings.max_agent_attempts):
            client.portal.call(app.supervisor.workers["tasks-0"].run_once)
        row = task_row(app, identity)
        assert row["status"] == "failed" and row["mode"] == "decision"
        assert row["attempt_count"] == settings.max_agent_attempts
        assert row["last_invocation_json"] is None and row["last_run_json"] is None
        with app.database.read() as connection:
            assert (
                app.game_queries.participant_context(
                    connection, "community", CHARACTER, game
                ).game.state_version
                == row["state_version"]
            )
            assert connection.execute("SELECT COUNT(*) FROM activity_results").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0] == 0
        assert (
            source.message_id
            in app.activity_context.pending_sources("community", "first", game)["message_ids"]
        )


def test_cleanup_waits_for_active_activity_dispatcher_after_pause(client):
    activity_game(client)
    app = client.app.state.application
    app.activity_coordinator.scan()
    worker = app.supervisor.workers["tasks-0"]
    backend = app.activity_execution.agents.bindings[InvocationPurpose.ACTIVITY_TURN].backend
    budget = backend._loop.gateway
    slots = AsyncExitStack()

    async def occupy_and_dispatch():
        for _ in range(app.settings.model_concurrency):
            await slots.enter_async_context(budget.slot())
        task = asyncio.create_task(worker.run_once())
        async with asyncio.timeout(10):
            while not budget._waiting:
                assert not task.done()
                await asyncio.sleep(0.01)
        return task

    task = client.portal.call(occupy_and_dispatch)
    try:
        identity = worker.dispatcher.active_task_id
        app.communities.update("community", expected_version=1, status="paused")
        assert task_row(app, identity)["status"] == "suspended"
        preview = client.post(
            "/internal/maintenance/cleanup", json={"community_ids": ["community"]}
        )
        assert preview.status_code == 200, preview.text
        assert any(
            item["kind"] == "runtime_task" and item["object_id"] == identity
            for item in preview.json()["blockers"]
        )
        blocked = client.post(
            "/internal/maintenance/cleanup",
            json={"community_ids": ["community"], "dry_run": False},
        )
        assert blocked.status_code == 409, blocked.text
    finally:

        async def release():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await slots.aclose()

        client.portal.call(release)
    assert worker.dispatcher.active_task_id is None
    cleaned = client.post(
        "/internal/maintenance/cleanup",
        json={"community_ids": ["community"], "dry_run": False},
    )
    assert cleaned.status_code == 200, cleaned.text
