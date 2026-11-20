import json

import pytest
from fastapi.testclient import TestClient
from support.application import settings_for
from support.http import create_group

from echo_commons.app.main import create_app
from echo_commons.modules.social.settings import ParticipationSettings


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
