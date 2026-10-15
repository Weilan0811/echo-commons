from concurrent.futures import ThreadPoolExecutor
from uuid import uuid4

from fastapi.testclient import TestClient
from support.application import settings_for
from support.http import create_group
from support.migrations import load_history

from echo_commons.app.main import create_app
from echo_commons.infrastructure.database.migrations import initialize

BASE = "/api/conversations/conversation"


def summary(client, identity="conversation", player="alice"):
    response = client.get(f"/api/conversations/{identity}", params={"player_id": player})
    assert response.status_code == 200, response.text
    return response.json()


def leave(client, identity="conversation", player="alice"):
    before = summary(client, identity, player)
    response = client.delete(
        f"/api/conversations/{identity}/membership",
        params={
            "player_id": player,
            "client_operation_id": str(uuid4()),
            "expected_membership_id": before["self_membership_id"],
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def send(client, text, player="alice", identity="conversation"):
    response = client.post(
        f"/api/conversations/{identity}/messages",
        json={
            "player_id": player,
            "client_message_id": str(uuid4()),
            "text": text,
        },
    )
    assert response.status_code == 202, response.text
    return response.json()


def listing(client, view, player="alice"):
    response = client.get("/api/conversations", params={"player_id": player, "view": view})
    assert response.status_code == 200, response.text
    return {row["conversation_id"]: row for row in response.json()["items"]}


def direct(client, identity=None, reverse=False):
    actors = [{"kind": "player", "actor_id": "alice"}, {"kind": "character", "actor_id": "first"}]
    response = client.post(
        "/api/communities/community/conversations",
        json={
            "player_id": "alice",
            "kind": "direct",
            "conversation_id": identity or str(uuid4()),
            "actors": actors[::-1] if reverse else actors,
        },
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_private_pair_concurrent_open_and_reentry_keep_identity(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        with ThreadPoolExecutor(max_workers=4) as pool:
            rows = list(pool.map(lambda index: direct(client, reverse=index % 2 == 0), range(4)))
        identity = rows[0]["conversation_id"]
        assert {row["conversation_id"] for row in rows} == {identity}
        original = summary(client, identity)["self_membership_id"]
        send(client, "原有私聊", identity=identity)
        leave(client, identity)
        reopened = direct(client)
        assert reopened["conversation_id"] == identity
        assert summary(client, identity)["self_membership_id"] != original
        app = client.app.state.application
        app.conversations.archive("community", identity)
        assert direct(client)["status"] == "active"
        with app.database.read() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM direct_conversation_pairs").fetchone()[0]
                == 1
            )
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_group_reentry_hides_departure_gap_and_preserves_old_messages(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        old = send(client, "退出前可以看见")
        leave(client)
        gap = send(client, "退出期间不可见", player="bob")
        assert "conversation" not in listing(client, "active")
        assert "conversation" in listing(client, "history")
        result = client.put(
            BASE + "/membership", json={"player_id": "alice", "client_operation_id": str(uuid4())}
        )
        assert result.status_code == 200, result.text
        new = send(client, "重新加入后可以看见", player="bob")
        history = client.get(BASE + "/messages/history", params={"player_id": "alice"}).json()
        ids = {row["message_id"] for row in history["messages"]}
        assert (
            old["message_id"] in ids and new["message_id"] in ids and gap["message_id"] not in ids
        )


def test_archive_permissions_versions_dedup_and_task_cancellation(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        assert summary(client)["creator_display"]["display_name"] == "alice"
        assert not summary(client, player="bob")["can_archive"]
        body = {
            "player_id": "bob",
            "expected_state_version": 1,
            "client_operation_id": str(uuid4()),
        }
        assert client.post(BASE + "/archive", json=body).status_code == 404
        body.update(player_id="alice", expected_state_version=999, client_operation_id=str(uuid4()))
        assert client.post(BASE + "/archive", json=body).status_code == 409
        send(client, "请两位角色回复")
        app = client.app.state.application
        app.intake.quiet_seconds = 0
        with app.database.transaction() as connection:
            connection.execute("UPDATE input_batches SET quiet_until_utc=created_at_utc")
        assert app.planner.plan()
        body.update(expected_state_version=1, client_operation_id=str(uuid4()))
        response = client.post(BASE + "/archive", json=body)
        assert response.status_code == 200, response.text
        assert client.post(BASE + "/archive", json=body).json() == response.json()
        assert summary(client)["state_version"] == 2 and not summary(client)["can_send"]
        assert (
            client.put(
                BASE + "/membership",
                json={"player_id": "alice", "client_operation_id": str(uuid4())},
            ).status_code
            == 409
        )
        assert (
            client.post(
                BASE + "/messages",
                json={"player_id": "bob", "text": "迟到消息", "client_message_id": str(uuid4())},
            ).status_code
            == 409
        )
        assert "conversation" in listing(client, "archived")
        with app.database.read() as connection:
            assert not connection.execute(
                "SELECT 1 FROM conversation_tasks "
                "WHERE status IN ('pending','processing','retry_wait','suspended')"
            ).fetchall()
            assert not connection.execute(
                "SELECT 1 FROM social_chains WHERE status='active'"
            ).fetchall()


def test_last_player_leaving_archives_group_but_one_remaining_player_keeps_it(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        leave(client)
        assert summary(client, player="bob")["status"] == "active"
        leave(client, player="bob")
        assert summary(client)["status"] == "archived"
        assert not summary(client)["can_join"]


def test_hidden_preferences_are_personal_and_private_message_restores_list(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        request = {"player_id": "alice", "hidden": True, "client_operation_id": str(uuid4())}
        response = client.put(BASE + "/list-preference", json=request)
        assert response.status_code == 200
        assert client.put(BASE + "/list-preference", json=request).json() == response.json()
        assert "conversation" not in listing(client, "active")
        assert "conversation" in listing(client, "hidden")
        assert "conversation" in listing(client, "active", "bob")
        request["hidden"] = False
        assert client.put(BASE + "/list-preference", json=request).status_code == 409
        request["client_operation_id"] = str(uuid4())
        assert client.put(BASE + "/list-preference", json=request).status_code == 200
        identity = direct(client)["conversation_id"]
        request.update(hidden=True, client_operation_id=str(uuid4()))
        assert (
            client.put(f"/api/conversations/{identity}/list-preference", json=request).status_code
            == 200
        )
        send(client, "私聊的新消息", identity=identity)
        assert identity in listing(client, "active") and not summary(client, identity)["hidden"]


def test_player_exit_stops_root_response_and_unplanned_input(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        app = client.app.state.application
        app.intake.quiet_seconds = 0
        send(client, "请回复我")
        assert app.planner.plan()
        leave(client)
        with app.database.read() as connection:
            assert not connection.execute(
                "SELECT 1 FROM conversation_tasks "
                "WHERE status IN ('pending','processing','retry_wait')"
            ).fetchall()
        client.put(
            BASE + "/membership", json={"player_id": "alice", "client_operation_id": str(uuid4())}
        )
        send(client, "这个输入尚未安排")
        leave(client)
        assert app.planner.plan()
        assert not app.planner.plan()
        with app.database.read() as connection:
            assert not connection.execute(
                "SELECT 1 FROM social_chains WHERE status='active'"
            ).fetchall()


def test_version_sixteen_duplicate_and_ownerless_group_migration_preserves_history(tmp_path):
    old = load_history(16, tmp_path / "old.sqlite3")
    with old.read() as connection:
        segment_id = connection.execute("SELECT segment_id FROM memory_segments").fetchone()[0]
    with old.transaction() as connection:
        for identity, status, created in (
            ("original", "active", "2000-01-01T00:00:00+00:00"),
            ("duplicate", "active", "2001-01-01T00:00:00+00:00"),
        ):
            connection.execute(
                "INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)",
                (identity, "community", "direct", status, 2, 1, created, created),
            )
            for kind, actor in (("player", "alice"), ("character", "first")):
                connection.execute(
                    "INSERT INTO conversation_memberships VALUES (?,?,?,?,?,?,?,?,?)",
                    (str(uuid4()), "community", identity, kind, actor, 0, None, created, None),
                )
        connection.execute(
            "UPDATE conversation_memberships SET left_at_sequence=0,left_at_utc=joined_at_utc "
            "WHERE conversation_id='conversation' AND actor_kind='player'"
        )
        connection.execute(
            "INSERT INTO conversations VALUES (?,?,?,?,?,?,?,?)",
            ("old-small", "community", "group", "active", 2, 1, created, created),
        )
        for kind, actor in (("player", "alice"), ("character", "first")):
            connection.execute(
                "INSERT INTO conversation_memberships VALUES (?,?,?,?,?,?,?,?,?)",
                (str(uuid4()), "community", "old-small", kind, actor, 0, None, created, None),
            )
    initialize(old)
    with old.read() as connection:
        assert (
            connection.execute("SELECT conversation_id FROM direct_conversation_pairs").fetchone()[
                0
            ]
            == "original"
        )
        assert (
            connection.execute(
                "SELECT status FROM conversations WHERE conversation_id='duplicate'"
            ).fetchone()[0]
            == "archived"
        )
        assert connection.execute(
            "SELECT status,creator_player_id FROM conversations "
            "WHERE conversation_id='conversation'"
        ).fetchone()[:] == ("archived", None)
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert connection.execute(
            "SELECT kind,status,legacy_small_group FROM conversations "
            "WHERE conversation_id='old-small'"
        ).fetchone()[:] == ("group", "active", 1)
        assert (
            connection.execute(
                "SELECT segment_id FROM memory_segments WHERE segment_id=?", (segment_id,)
            ).fetchone()[0]
            == segment_id
        )
        assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] > 0
        assert not connection.execute(
            "SELECT 1 FROM conversation_tasks WHERE status!='cancelled'"
        ).fetchall()
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
