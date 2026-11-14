import asyncio
import json
from contextlib import AsyncExitStack

import pytest
from fastapi.testclient import TestClient
from support.activities import message
from support.application import settings_for
from support.migrations import load_history

from echo_commons.agents.contracts.activity import (
    ActivityExpressionInput,
)
from echo_commons.agents.contracts.invocation import InvocationPurpose
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.execution.lease import LeaseLostError
from echo_commons.infrastructure.database.errors import StorageError


@pytest.mark.model
def test_cleanup_tracks_expression_in_unified_dispatcher_after_pause(tmp_path):
    from test_activity_coordination import plan_reply, waiting_game
    from test_activity_models import decision_settings

    with TestClient(create_app(decision_settings(tmp_path))) as client:
        game = waiting_game(client)
        plan_reply(client, game, "嗨，小槿，开局前跟我打声招呼吧~")
        app = client.app.state.application
        lease = client.portal.call(app.activity_queue.claim, "local-greeting", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        assert artifact["mode"] == "decision"
        assert artifact["run"]["output"]["payload"]["expression_needed"]
        result = app.activity_commit.commit(lease, artifact)
        worker = app.supervisor.workers["tasks-0"]
        backend = app.activity_execution.agents.bindings[
            InvocationPurpose.ACTIVITY_EXPRESSION
        ].backend
        budget = backend._loop.gateway
        slots = AsyncExitStack()

        async def occupy_and_dispatch():
            for _ in range(app.settings.model_concurrency):
                await slots.enter_async_context(budget.slot())
            running = asyncio.create_task(worker.run_once())
            async with asyncio.timeout(20):
                while not budget._waiting:
                    assert not running.done()
                    await asyncio.sleep(0.01)
            return running

        running = client.portal.call(occupy_and_dispatch)
        try:
            assert worker.dispatcher.active_task_id == result["result_id"]
            app.communities.update("community", expected_version=1, status="paused")
            preview = client.post(
                "/internal/maintenance/cleanup", json={"community_ids": ["community"]}
            )
            assert preview.status_code == 200, preview.text
            assert any(
                item["kind"] == "runtime_task" and item["object_id"] == result["result_id"]
                for item in preview.json()["blockers"]
            )
        finally:

            async def release():
                running.cancel()
                await asyncio.gather(running, return_exceptions=True)
                await slots.aclose()

            client.portal.call(release)
        assert worker.dispatcher.active_task_id is None
        cleaned = client.post(
            "/internal/maintenance/cleanup", json={"community_ids": ["community"], "dry_run": False}
        )
        assert cleaned.status_code == 200, cleaned.text
        with app.database.read() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM execution_scheduling").fetchone()[0] == 1
            )
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.model
def test_upgrade_recovers_authentic_pending_expression_without_regenerating_body(tmp_path):
    database = load_history(31, tmp_path / "history.sqlite3")
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"database_path": str(database.path)}
    )
    with TestClient(create_app(settings)) as client:
        app = client.app.state.application
        with database.read() as connection:
            original = dict(connection.execute("SELECT * FROM activity_results").fetchone())
            expected = json.loads(original["expression_json"])["message"]["utterance"]
        client.portal.call(app.activity_queue.recover, utc_now())
        assert (
            client.portal.call(app.activity_expressions.queue.claim, "before-legacy", utc_now())
            is None
        )
        legacy = client.portal.call(app.queue.claim, "legacy-first", utc_now())
        client.portal.call(app.handler.execute, legacy)
        client.portal.call(app.activity_queue.recover, utc_now())
        lease = client.portal.call(
            app.activity_expressions.queue.claim, "authentic-expression", utc_now()
        )
        assert lease is not None
        client.portal.call(app.activity_expressions.execute, lease)
        with database.read() as connection:
            saved = connection.execute(
                "SELECT * FROM messages WHERE activity_result_id=?", (original["result_id"],)
            ).fetchone()
            assert saved["text"] == expected and saved["result_id"] is None
            assert (
                connection.execute(
                    "SELECT receipt_json FROM activity_results WHERE result_id=?",
                    (original["result_id"],),
                ).fetchone()[0]
                == original["receipt_json"]
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM task_execution_events WHERE "
                    "task_kind='activity_expression' AND event_kind='run_finished'"
                ).fetchone()[0]
                == 0
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM thoughts WHERE activity_result_id=?",
                    (original["result_id"],),
                ).fetchone()[0]
                == 1
            )
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        with pytest.raises(LeaseLostError):
            app.activity_expressions.prepare(lease)


@pytest.mark.model
def test_real_game_reply_publishes_joint_body_and_finishes_social(tmp_path):
    from support.games import create, operation
    from support.http import create_group

    settings = settings_for(tmp_path, workers=False).model_copy(
        update={
            "max_chain_tasks": 1,
            "debug_capture_enabled": True,
            "debug_capture_path": str(tmp_path / "captures"),
        }
    )
    with TestClient(create_app(settings)) as client:
        create_group(client, memory_mode="simple")
        game, _ = create(client)
        identity = game["game_id"]
        operation(
            client,
            identity,
            "participants",
            seat_id="white",
            participant={"kind": "character", "character_id": "first"},
        )
        app = client.app.state.application
        sent = message(client, identity, "小槿，你想先下黑棋还是白棋呀？说说你的想法吧。")
        app.planner.plan()
        app.activity_coordinator.scan()
        lease = client.portal.call(app.activity_queue.claim, "real-reply", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        result = app.activity_commit.commit(lease, artifact)
        assert artifact["run"]["output"]["payload"]["expression"] is not None
        with app.database.read() as connection:
            publication = app.activity_commit.results.for_task(connection, lease.task_id)
            assert publication["publication_status"] == "pending"
        app.activity_coordinator.scan()
        expression = client.portal.call(
            app.activity_expressions.queue.claim, "joint-body", utc_now()
        )
        client.portal.call(app.activity_expressions.execute, expression)
        with app.database.read() as connection:
            saved = connection.execute(
                "SELECT * FROM messages WHERE activity_result_id=?", (result["result_id"],)
            ).fetchone()
            assert saved is not None
            publication = app.activity_commit.results.for_task(connection, lease.task_id)
            assert publication["publication_status"] == "published"
            source = connection.execute(
                "SELECT * FROM activity_task_sources WHERE task_id=?", (lease.task_id,)
            ).fetchone()
            assert source["status"] == "published"
            turn = app.planner.social.by_id(connection, source["social_turn_id"])
            assert app.planner.social.chain(connection, turn.chain_id).message_count == 1
            assert not app.planner.social.awaiting_expression(connection, turn.chain_id)
            assert (
                sent.message_id in artifact["invocation"]["execution_policy"]["output_instructions"]
            )
        exported = app.conversation_export.export(
            "community", sent.conversation_id, first_sequence=1, through_sequence=2
        )
        assert any(
            ref["source_kind"] == "activity_result" and ref["source_id"] == result["result_id"]
            for ref in exported["references"]
        )
        assert not exported["results"]
        app.communities.update("community", expected_version=1, status="paused")
        cleanup = client.post(
            "/internal/maintenance/cleanup", json={"community_ids": ["community"], "dry_run": False}
        )
        assert cleanup.status_code == 200, cleanup.text
        assert cleanup.json()["counts"]["activity_expression_tasks"] == 1
        with app.database.read() as connection:
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.model
@pytest.mark.parametrize("failure_target", ["publication", "preparation"])
def test_local_expression_restarts_after_actual_storage_failure(tmp_path, failure_target):
    from test_activity_coordination import plan_reply, waiting_game
    from test_activity_models import decision_settings

    settings = decision_settings(tmp_path).model_copy(update={"retry_backoff_seconds": 0})
    with TestClient(create_app(settings)) as client:
        app = client.app.state.application
        game = waiting_game(client)
        identity, _, _ = plan_reply(client, game, "嗨，小槿，开局前跟我打声招呼吧~")
        lease = client.portal.call(app.activity_queue.claim, "local-greeting", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        assert artifact["mode"] == "decision"
        result = app.activity_commit.commit(lease, artifact)
        assert artifact["run"]["output"]["payload"]["expression_needed"]
        app.communities.update("community", expected_version=1, status="paused")
        assert client.portal.call(app.activity_expressions.queue.claim, "paused", utc_now()) is None
        app.communities.update("community", expected_version=2, status="active")
        client.portal.call(app.activity_expressions.queue.recover, utc_now())
        expression = client.portal.call(
            app.activity_expressions.queue.claim, "expression", utc_now()
        )
        with app.database.transaction() as connection:
            if failure_target == "publication":
                connection.execute(
                    "CREATE TRIGGER reject_expression BEFORE INSERT ON messages "
                    "WHEN NEW.activity_result_id IS NOT NULL "
                    "BEGIN SELECT RAISE(ABORT,'verification write failure'); END"
                )
            else:
                connection.execute(
                    "CREATE TRIGGER reject_expression BEFORE UPDATE OF prepared_json ON "
                    "activity_expression_tasks "
                    "WHEN NEW.prepared_json IS NOT NULL "
                    "BEGIN SELECT RAISE(ABORT,'verification write failure'); END"
                )
        with pytest.raises(StorageError):
            client.portal.call(app.activity_expressions.execute, expression)
        with app.database.transaction() as connection:
            saved = dict(connection.execute("SELECT * FROM activity_expression_tasks").fetchone())
            assert saved["last_run_json"]
            assert bool(saved["prepared_json"]) == (failure_target == "publication")
            assert (
                connection.execute("SELECT publication_status FROM activity_results").fetchone()[0]
                == "pending"
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE activity_result_id IS NOT NULL"
                ).fetchone()[0]
                == 0
            )
            connection.execute("DROP TRIGGER reject_expression")
        snapshot = ActivityExpressionInput.model_validate_json(saved["input_json"])
        proposal = app.activity_expressions.outputs.restore_result(
            saved["last_run_json"]
        ).output.payload
        blocker = app.database.connect()
        try:
            blocker.execute("BEGIN IMMEDIATE")
            with pytest.raises(StorageError) as failure:
                app.activity_expressions.publish(expression, snapshot, proposal)
            assert failure.value.retryable
        finally:
            blocker.rollback()
            blocker.close()
        client.portal.call(
            app.activity_expressions.queue.apply_recovery,
            expression,
            utc_now(),
            app.activity_expressions.queue.recovery.classify(failure.value),
        )
    with TestClient(create_app(settings)) as client:
        app = client.app.state.application
        newer = client.portal.call(app.activity_expressions.queue.claim, "after-restart", utc_now())
        assert newer.task_id == result["result_id"] and newer.generation > expression.generation
        client.portal.call(app.activity_expressions.execute, newer)
        with app.database.read() as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM messages WHERE activity_result_id=?",
                    (result["result_id"],),
                ).fetchone()[0]
                == 1
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM task_execution_events WHERE "
                    "task_kind='activity_expression' AND event_kind='run_finished'"
                ).fetchone()[0]
                == 1
            )
            assert connection.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0] == 0
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
