import json
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.application import settings_for
from support.http import create_group

from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.modules.characters.domain.instance import AvailabilityStatus
from echo_commons.modules.social.settings import ParticipationSettings
from echo_commons.shared.actors import ActorRef


@pytest.mark.parametrize("mode", ("remote_rules", "remote_willingness", "local_willingness"))
def test_modes_freeze_candidates_without_calling_models(tmp_path, mode):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"participation": ParticipationSettings(mode=mode)}
    )
    with TestClient(create_app(settings)) as client:
        create_group(client)
        response = client.post(
            "/api/conversations/conversation/messages",
            json={
                "player_id": "alice",
                "client_message_id": "opportunity",
                "text": "大家有什么想法？我想听听你们的意见。",
            },
        )
        assert response.status_code == 202
        app = client.app.state.application
        assert len(app.planner.plan()) == 1
        with app.database.read() as conn:
            batches = conn.execute("SELECT * FROM social_willingness_batches").fetchall()
            tasks = conn.execute("SELECT * FROM conversation_tasks").fetchall()
            if mode == "remote_rules":
                assert not batches and len(tasks) == 1
            else:
                assert len(batches) == 1 and len(tasks) == 2
                configuration = json.loads(batches[0]["configuration_json"])
                assert configuration["mode"] == mode
                snapshots = [
                    app.handler.execution.tasks.snapshot(conn, t["task_id"]) for t in tasks
                ]
                assert len({s.scope.observation_upper_sequence for s in snapshots}) == 1
                assert len({s.snapshot_id for s in snapshots}) == 2
                assert {s.scope.character_id for s in snapshots} == {"first", "second"}
                assert all(
                    app.queue.repository.kind(conn, t["task_id"]) == "social_willingness"
                    for t in tasks
                )
                assert "credential" not in configuration["model"]
            assert not conn.execute("PRAGMA foreign_key_check").fetchall()
        assert app.gateway.usage_tracker.snapshot() == {}
        assert bool(app.decisions) == (mode == "local_willingness")
        assert app.planner.plan() == ()


def test_willingness_checks_expression_quota_before_creating_judgments(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={
            "participation": ParticipationSettings(mode="remote_willingness"),
            "max_chain_tasks": 1,
        }
    )
    with TestClient(create_app(settings)) as client:
        create_group(client)
        assert (
            client.post(
                "/api/conversations/conversation/messages",
                json={
                    "player_id": "alice",
                    "client_message_id": "quota",
                    "text": "大家一起讨论吧。",
                },
            ).status_code
            == 202
        )
        app = client.app.state.application
        app.planner.plan()
        with app.database.read() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM social_willingness_tasks").fetchone()[0]
                == 0
            )
            assert (
                connection.execute("SELECT stop_reason FROM social_chains").fetchone()[0]
                == "task_limit"
            )
        assert app.gateway.usage_tracker.snapshot() == {}


@pytest.mark.parametrize("activity_enabled", (False, True))
@pytest.mark.parametrize("mode", ("remote_rules", "remote_willingness", "local_willingness"))
def test_group_and_activity_local_input_limits_are_independent(tmp_path, activity_enabled, mode):
    settings = settings_for(tmp_path, workers=False)
    registry = tmp_path / "models.toml"
    registry.write_text(
        Path(settings.model_registry_path).read_text(encoding="utf-8").replace(
            "[decision]\nenabled = false", f"[decision]\nenabled = {str(activity_enabled).lower()}"
        ),
        encoding="utf-8",
    )
    settings = settings.model_copy(
        update={
            "model_registry_path": str(registry),
            "participation": ParticipationSettings(mode=mode),
        }
    )
    with TestClient(create_app(settings)) as client:
        app = client.app.state.application
        assert app.models.decision.enabled == activity_enabled
        assert bool(app.planner.judgments.context.input_budget.additional_limits) == (
            mode == "local_willingness"
        )
        assert bool(app.activity_execution.decisions) == activity_enabled
        for kind, budget in app.activity_context.input_budgets.items():
            assert bool(budget.additional_limits) == (activity_enabled and kind != "expression")
        assert app.gateway.usage_tracker.snapshot() == {}


def test_missing_credentials_remain_a_batch_failure(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={
            "model_secrets_path": str(tmp_path / "absent-secrets.toml"),
            "participation": ParticipationSettings(mode="remote_willingness"),
        }
    )
    with TestClient(create_app(settings)) as client:
        create_group(client)
        assert client.post(
            "/api/conversations/conversation/messages",
            json={
                "player_id": "alice", "client_message_id": "missing-key", "text": "大家聊聊吧。"
            },
        ).status_code == 202
        app = client.app.state.application
        app.planner.plan()
        for _ in range(8):
            if not client.portal.call(app.supervisor.workers["conversation-memory"].run_once):
                break
        for _ in range(2):
            assert client.portal.call(app.supervisor.workers["tasks-0"].run_once)
        app.planner.plan()
        with app.database.read() as connection:
            rows = connection.execute(
                "SELECT status,last_error_code FROM conversation_tasks"
            ).fetchall()
            assert len(rows) == 2
            assert all(tuple(row) == ("failed", "provider_not_configured") for row in rows)
            assert connection.execute(
                "SELECT status FROM social_willingness_batches"
            ).fetchone()[0] == "failed"
            assert connection.execute(
                "SELECT stop_reason FROM social_chains"
            ).fetchone()[0] == "judgment_failed"
        assert app.gateway.usage_tracker.snapshot() == {}


@pytest.mark.model
@pytest.mark.parametrize("change", ("leave_before", "leave_after", "busy_after"))
def test_real_willingness_keeps_eligible_scores_when_another_candidate_becomes_unavailable(
    tmp_path, change, record_testsuite_property
):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={
            "participation": ParticipationSettings(mode="remote_willingness", threshold=0),
            "debug_capture_enabled": True,
            "debug_capture_path": str(tmp_path / "calls"),
        }
    )
    with TestClient(create_app(settings)) as client:
        create_group(client)
        assert client.post(
            "/api/conversations/conversation/messages",
            json={
                "player_id": "alice",
                "client_message_id": "departure",
                "text": "大家最近画画怎么样？想听听你们的新想法。",
            },
        ).status_code == 202
        app = client.app.state.application
        assert len(app.planner.plan()) == 1
        if change == "leave_before":
            app.conversations.leave("community", "conversation", ActorRef("character", "second"))
        for _ in range(8):
            if not client.portal.call(app.supervisor.workers["conversation-memory"].run_once):
                break
        for _ in range(1 if change == "leave_before" else 2):
            lease = client.portal.call(app.queue.claim, "candidate-change", utc_now())
            assert lease is not None and lease.task_kind == "social_willingness"
            client.portal.call(app.planner.judgments.execute, lease)
        if change == "leave_after":
            app.conversations.leave("community", "conversation", ActorRef("character", "second"))
        elif change == "busy_after":
            app.character_state.set_availability(
                "community", "second", AvailabilityStatus.BUSY, expected_version=0
            )
        assert len(app.planner.plan()) == 1
        with app.database.read() as connection:
            batch = connection.execute("SELECT * FROM social_willingness_batches").fetchone()
            assert batch["status"] == "selected" and batch["selected_character_id"] == "first"
            assert set(json.loads(batch["selection_json"])["scores"]) == {"first"}
            rows = connection.execute(
                "SELECT t.character_id,j.expression_selected,j.result_json "
                "FROM social_willingness_tasks j JOIN conversation_tasks t USING(task_id)"
            ).fetchall()
            assert all(bool(row["expression_selected"]) == (row["character_id"] == "first")
                       for row in rows)
            decision = connection.execute(
                "SELECT status,outcome FROM participation_decisions WHERE character_id='second'"
            ).fetchone()
            assert tuple(decision) == ("cancelled", "cancelled")
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
            record_testsuite_property(change, json.dumps([dict(row) for row in rows]))
