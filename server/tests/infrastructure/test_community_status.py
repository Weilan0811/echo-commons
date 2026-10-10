import asyncio
from datetime import UTC, datetime, timedelta

from fastapi.testclient import TestClient
from test_application_lifecycle import settings_for
from test_http_api import create_group

from echo_commons.app.main import create_app


def test_status_api_requires_membership_and_current_version_and_survives_restart(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    with TestClient(create_app(settings)) as client:
        for player in ("owner", "outsider"):
            assert (
                client.post(
                    "/api/players", json={"player_id": player, "display_name": player}
                ).status_code
                == 201
            )
        body = {"player_id": "owner", "community_id": "community", "name": "社群"}
        created = client.post("/api/communities", json=body).json()
        assert created["status"] == "paused" and created["state_version"] == 0
        capabilities = {"can_change_cover": True, "can_change_status": True}
        assert created["capabilities"] == capabilities
        assert (
            client.get("/api/communities/community", params={"player_id": "outsider"}).status_code
            == 404
        )
        url = "/api/communities/community/status"
        change = {"player_id": "owner", "status": "active", "expected_version": 0}
        assert client.patch(url, json=change | {"player_id": "outsider"}).status_code == 404
        assert client.patch(url, json=change | {"status": "invalid"}).status_code == 422
        assert client.patch(url, json=change | {"expected_version": -1}).status_code == 422
        assert client.patch(url, json=change | {"world_time_utc": "unexpected"}).status_code == 422
        active = client.patch(url, json=change)
        assert active.status_code == 200
        assert active.json()["status"] == "active" and active.json()["state_version"] == 1
        assert active.json()["capabilities"] == capabilities
        assert client.patch(url, json=change).status_code == 409
        repeated = client.patch(url, json=change | {"expected_version": 1})
        assert repeated.json() == active.json()
        assert client.post("/api/communities", json=body).json()["status"] == "active"
        paused = client.patch(url, json=change | {"status": "paused", "expected_version": 1})
        assert paused.status_code == 200 and paused.json()["state_version"] == 2
    with TestClient(create_app(settings)) as client:
        saved = client.get("/api/communities/community", params={"player_id": "owner"}).json()
        assert saved["status"] == "paused" and saved["state_version"] == 2


def test_joined_member_cover_and_status_share_authoritative_version(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        for player in ("creator", "member", "outsider"):
            assert (
                client.post(
                    "/api/players", json={"player_id": player, "display_name": player}
                ).status_code
                == 201
            )
        created = client.post(
            "/api/communities",
            json={
                "player_id": "creator",
                "community_id": "world",
                "name": "校园",
                "timezone": "Asia/Shanghai",
            },
        ).json()
        assert created["timezone"] == "Asia/Shanghai"
        assert client.put("/api/communities/world/players/member").status_code == 200
        member = client.get("/api/communities/world", params={"player_id": "member"}).json()
        assert member["capabilities"] == created["capabilities"]
        cover = {
            "player_id": "member",
            "expected_version": 0,
            "cover_kind": "preset",
            "cover_ref": "diner",
        }
        assert (
            client.patch(
                "/api/communities/world/appearance", json=cover | {"player_id": "outsider"}
            ).status_code
            == 404
        )
        saved = client.patch("/api/communities/world/appearance", json=cover).json()
        assert saved["cover_ref"] == "diner" and saved["state_version"] == 1
        assert saved["capabilities"] == member["capabilities"]
        status = {"player_id": "member", "expected_version": 0, "status": "active"}
        assert client.patch("/api/communities/world/status", json=status).status_code == 409
        active = client.patch(
            "/api/communities/world/status", json=status | {"expected_version": 1}
        ).json()
        assert active["state_version"] == 2 and active["cover_ref"] == "diner"
        cleared = client.patch(
            "/api/communities/world/appearance",
            json=cover
            | {
                "expected_version": 2,
                "cover_kind": None,
                "cover_ref": None,
            },
        ).json()
        assert cleared["state_version"] == 3 and cleared["cover_ref"] is None
        assert cleared["status"] == "active"


def test_paused_community_excluded_from_memory_scan_and_task_claims(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client:
        create_group(client, memory_mode="simple")
        assert (
            client.post(
                "/api/conversations/conversation/messages",
                json={
                    "player_id": "alice",
                    "client_message_id": "hello",
                    "text": "今天一起做晚饭。",
                },
            ).status_code
            == 202
        )
        application = app.state.application
        url = "/api/communities/community/status"
        change = {"player_id": "alice", "status": "paused", "expected_version": 1}
        assert client.patch(url, json=change).status_code == 200
        now = datetime.now(UTC) + timedelta(hours=3)
        assert application.supervisor.workers["memory-cycles"].scan(now) == 0
        assert asyncio.run(application.reflection_queue.claim("worker", datetime.now(UTC))) is None
        assert asyncio.run(application.queue.claim("worker", datetime.now(UTC))) is None
        with application.database.read() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM reflection_graph_runs").fetchone()[0] == 0
            )
        assert (
            client.patch(url, json=change | {"status": "active", "expected_version": 2}).status_code
            == 200
        )
        assert application.supervisor.workers["memory-cycles"].scan(now) == 2
        with application.database.read() as connection:
            original_nodes = tuple(
                connection.execute(
                    "SELECT node_task_id FROM reflection_node_tasks ORDER BY node_task_id"
                )
            )
        assert client.patch(url, json=change | {"expected_version": 3}).status_code == 200
        assert asyncio.run(application.reflection_queue.claim("worker", datetime.now(UTC))) is None
        assert application.supervisor.workers["memory-cycles"].scan(now) == 0
        assert (
            client.patch(url, json=change | {"status": "active", "expected_version": 4}).status_code
            == 200
        )
        lease = asyncio.run(application.reflection_queue.claim("worker", datetime.now(UTC)))
        assert lease is not None and lease.task_id in {row[0] for row in original_nodes}
        assert application.gateway._clients == {}
