import asyncio
import json
import socket
from dataclasses import replace
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.application import settings_for
from support.http import create_group
from support.social import build_planning_system, send

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.main import create_app
from echo_commons.execution.lease import LeaseLostError
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.infrastructure.models.decision_protocol import DecisionRequest
from echo_commons.infrastructure.models.protocol import ModelGatewayError


def configured(tmp_path, *, enabled, **changes):
    settings = settings_for(tmp_path, workers=False)
    registry = tmp_path / "models.toml"
    registry.write_text(
        Path(settings.model_registry_path)
        .read_text(encoding="utf-8")
        .replace("[decision]\nenabled = false", f"[decision]\nenabled = {str(enabled).lower()}"),
        encoding="utf-8",
    )
    return settings.model_copy(update={"model_registry_path": registry, **changes})


def plan(client, text="第一位，请你说说今天想做什么？"):
    response = client.post(
        "/api/conversations/conversation/messages",
        json={
            "player_id": "alice",
            "client_message_id": text,
            "text": text,
            "mentions": [{"kind": "character", "actor_id": "first"}],
        },
    )
    assert response.status_code == 202, response.text
    app = client.app.state.application
    app.planner.plan()
    with app.database.read() as connection:
        task = connection.execute(
            "SELECT * FROM conversation_tasks WHERE character_id='first' "
            "ORDER BY created_at_utc LIMIT 1"
        ).fetchone()
        assert task is not None
        snapshot = app.handler.execution.tasks.snapshot(connection, task["task_id"])
        judgment = dict(
            connection.execute(
                "SELECT * FROM social_participation_judgments WHERE task_id=?", (task["task_id"],)
            ).fetchone()
        )
    return task["task_id"], snapshot, judgment


@pytest.mark.parametrize("enabled", (False, True))
def test_social_judgment_freezes_shared_material_and_configuration(tmp_path, enabled):
    with TestClient(create_app(configured(tmp_path, enabled=enabled))) as client:
        create_group(client)
        task_id, snapshot, judgment = plan(client)
        app = client.app.state.application
        assert judgment["mode"] == ("decision" if enabled else "ordinary")
        assert judgment["choice"] is None
        assert app.gateway.usage_tracker.snapshot() == {}
        detail = client.get(
            f"/internal/characters/first/tasks/{task_id}", params={"community_id": "community"}
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["participation"]["mode"] == judgment["mode"]
        assert "request_json" not in detail.json()["participation"]
        if enabled:
            frozen = DecisionRequest.model_validate_json(judgment["request_json"])
            assert frozen.deadline_utc is None
            assert frozen.route.base_url == "http://127.0.0.1:8090"
            assert frozen.controls.think_mode == "never"
            material = json.dumps(frozen.state, ensure_ascii=False)
            assert snapshot.self.voice in frozen.state["角色及眼前情景"]
            assert snapshot.current_messages[0].text in material
            assert "只返回" not in frozen.questions["participation"].instructions
            app.decisions.registry = replace(
                app.decisions.registry,
                decision=(app.decisions.registry.decision.model_copy(update={"enabled": False})),
            )
            with app.database.read() as connection:
                assert (
                    connection.execute(
                        "SELECT request_json FROM social_participation_judgments WHERE task_id=?",
                        (task_id,),
                    ).fetchone()[0]
                    == judgment["request_json"]
                )
        else:
            assert app.decisions is None and judgment["request_json"] is None


def test_stale_lease_cannot_run_participation_or_consume_observation(tmp_path):
    with TestClient(create_app(configured(tmp_path, enabled=True))) as client:
        create_group(client)
        _, snapshot, _ = plan(client)
        app = client.app.state.application
        lease = asyncio.run(app.queue.claim("owner", datetime.now(UTC)))
        assert lease is not None
        with pytest.raises(LeaseLostError):
            asyncio.run(app.handler.participation.evaluate(replace(lease, owner="other"), snapshot))
        assert app.decisions._client is None
        with app.database.read() as connection:
            assert connection.execute("SELECT count(*) FROM social_observations").fetchone()[0] == 0


def test_explicit_initiation_skips_local_participation(tmp_path):
    with TestClient(create_app(configured(tmp_path, enabled=True))) as client:
        create_group(client)
        app = client.app.state.application
        task_id = app.conversation_initiations.request(
            "community",
            "conversation",
            "first",
            "你刚完成了一幅画，想请大家看看。",
            request_id="finished-painting",
        )
        with app.database.read() as connection:
            row = connection.execute(
                "SELECT * FROM social_participation_judgments WHERE task_id=?", (task_id,)
            ).fetchone()
            assert row["mode"] == "ordinary" and row["request_json"] is None
        assert app.decisions._client is None


def test_local_connection_failure_does_not_call_text_model_or_record_silence(tmp_path):
    with (
        socket.socket() as listener,
        TestClient(create_app(configured(tmp_path, enabled=True))) as client,
    ):
        listener.bind(("127.0.0.1", 0))
        app = client.app.state.application
        gateway = app.decisions
        entry = gateway.registry.resolve("decision")
        unavailable = replace(entry, base_url=f"http://127.0.0.1:{listener.getsockname()[1]}")
        gateway.registry = replace(
            gateway.registry, entries={**gateway.registry.entries, entry.entry_id: unavailable}
        )
        create_group(client)
        task_id, _, _ = plan(client)

        async def run():
            lease = await app.queue.claim("connection-check", datetime.now(UTC))
            with pytest.raises(ModelGatewayError):
                await app.handler.execute(lease)

        asyncio.run(run())
        assert app.gateway.usage_tracker.snapshot() == {}
        with app.database.read() as connection:
            assert (
                connection.execute(
                    "SELECT choice FROM social_participation_judgments WHERE task_id=?", (task_id,)
                ).fetchone()[0]
                is None
            )
            assert connection.execute("SELECT count(*) FROM social_observations").fetchone()[0] == 0


def test_version_26_tasks_keep_ordinary_execution_and_identical_snapshot(tmp_path):
    directory = tmp_path / "version26"
    directory.mkdir()
    for source in files("echo_commons.infrastructure.database.sql").iterdir():
        if source.name.endswith(".sql") and int(source.name[:4]) <= 26:
            (directory / source.name).write_text(
                source.read_text(encoding="utf-8"), encoding="utf-8"
            )
    system = build_planning_system(tmp_path, sql_directory=directory)
    send(system)
    system.planner.plan()
    with system.database.read() as connection:
        before = [
            tuple(row)
            for row in connection.execute("SELECT task_id,snapshot_json FROM conversation_tasks")
        ]
    assert initialize(system.database) == 27
    with system.database.read() as connection:
        assert before == [
            tuple(row)
            for row in connection.execute("SELECT task_id,snapshot_json FROM conversation_tasks")
        ]
        assert connection.execute(
            "SELECT count(*) FROM social_participation_judgments WHERE mode='ordinary'"
        ).fetchone()[0] == len(before)


@pytest.mark.model
@pytest.mark.asyncio
async def test_real_local_judgment_is_reused_after_process_restart(tmp_path):
    settings = configured(
        tmp_path,
        enabled=True,
        lease_seconds=30.0,
        lease_heartbeat_interval_seconds=0.1,
        lease_safety_margin_seconds=0.05,
        retry_backoff_seconds=0,
    )
    with TestClient(create_app(settings)) as client:
        create_group(client)
        _, snapshot, _ = plan(client, "第一位，我在直接问你：今天最想做哪件事？请说说你的想法。")
    async with application_lifecycle(settings) as app:
        lease = await app.queue.claim("first-process", datetime.now(UTC))
        # 为真实推理保留正常租约长度，使用共同心跳执行。
        from echo_commons.execution.lease import with_heartbeat

        verdict = await with_heartbeat(
            app.queue, lease, app.handler.participation.evaluate(lease, snapshot), 0.1
        )
        assert verdict.choice in ("participate", "silent", "understand")
    await asyncio.sleep(30.1)
    async with application_lifecycle(settings) as app:
        lease = await app.queue.claim("second-process", datetime.now(UTC))
        assert lease is not None and lease.attempt == 2
        restored = await app.handler.participation.evaluate(lease, snapshot)
        assert restored.reused and restored.choice == verdict.choice
        assert restored.usage.model_request_count == 0
        assert app.decisions._client is None
