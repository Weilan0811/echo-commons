from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from importlib.resources import files
from shutil import copytree

import pytest
import yaml
from fastapi.testclient import TestClient
from test_application_lifecycle import settings_for
from test_http_api import create_group

from echo_commons.app.main import create_app
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog
from echo_commons.modules.conversations.member_operations import MembershipOperation
from echo_commons.modules.perspective.contracts import ObservationScope
from echo_commons.modules.perspective.policy import visible_message_sql
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError


def get(client, path, player="bob", **params):
    response = client.get(path, params={"player_id": player, **params})
    assert response.status_code == 200, response.text
    return response.json()


def send(client, key, *, player="alice", private=False, reply=None):
    body = {"player_id": player, "client_message_id": key, "text": key}
    if private:
        body.update(
            visibility="recipients", recipients=[{"kind": "character", "actor_id": "first"}]
        )
    if reply:
        body["reply_to_message_id"] = reply
    response = client.post("/api/conversations/conversation/messages", json=body)
    assert response.status_code == 202, response.text
    return response.json()


def leave(client, player, operation, interval=None):
    if interval is None:
        interval = get(client, "/api/conversations/conversation", player)["self_membership_id"]
    return client.delete(
        "/api/conversations/conversation/membership",
        params={
            "player_id": player,
            "expected_membership_id": interval,
            "client_operation_id": operation,
        },
    )


def join(client, player, operation):
    return client.put(
        "/api/conversations/conversation/membership",
        json={"player_id": player, "client_operation_id": operation},
    )


def test_player_discovery_create_scope_and_management_lists(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        assert len(client.get("/api/players").json()["items"]) == 2
        assert client.get("/api/players/alice").json()["display_name"] == "alice"
        assert len(get(client, "/api/communities", "alice")["items"]) == 1
        assert get(client, "/api/communities", "alice", scope="available")["items"] == []
        assert (
            client.post(
                "/api/players", json={"player_id": "outside", "display_name": "访客"}
            ).status_code
            == 201
        )
        assert len(get(client, "/api/communities", "outside", scope="available")["items"]) == 1
        assert (
            client.get("/api/communities/community", params={"player_id": "outside"}).status_code
            == 404
        )
        assert (
            client.post(
                "/api/communities/community/characters",
                json={"player_id": "outside", "blueprint_id": "xiaojin"},
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/communities/community/conversations",
                json={
                    "player_id": "alice",
                    "kind": "direct",
                    "actors": [
                        {"kind": "player", "actor_id": "bob"},
                        {"kind": "character", "actor_id": "first"},
                    ],
                },
            ).status_code
            == 400
        )
        response = client.post(
            "/api/communities/community/conversations",
            json={
                "player_id": "alice",
                "conversation_id": "private",
                "kind": "direct",
                "actors": [
                    {"kind": "player", "actor_id": "alice"},
                    {"kind": "character", "actor_id": "first"},
                ],
            },
        )
        assert response.status_code == 201
        assert len(get(client, "/api/conversations", "alice")["items"]) == 2
        assert [item["conversation_id"] for item in get(client, "/api/conversations")["items"]] == [
            "conversation"
        ]
        assert (
            client.get("/api/conversations/private", params={"player_id": "bob"}).status_code == 404
        )
        page = get(client, "/api/conversations", "alice", limit=1)
        assert page["has_more"] and page["cursor"]
        assert (
            client.get(
                "/api/conversations", params={"player_id": "bob", "cursor": page["cursor"]}
            ).json()["error"]["code"]
            == "invalid_cursor"
        )
        second = get(client, "/api/conversations", "alice", cursor=page["cursor"], limit=1)
        assert second["items"][0]["conversation_id"] != page["items"][0]["conversation_id"]
        assert second["cursor"] is None and not second["has_more"]
        assert len(client.get("/internal/communities/community/conversations").json()["items"]) == 2
        assert len(client.get("/internal/communities/community/characters").json()["items"]) == 2
        assert len(get(client, "/api/communities/community/members")["items"]) == 4
        assert len(get(client, "/api/conversations/conversation/members")["items"]) == 4
        assert client.get("/api/communities/community/conversations").status_code == 405
        assert client.put("/api/conversations/conversation/members/player/bob").status_code == 404
        assert client.post("/api/communities", json={"name": "无发起者"}).status_code == 422


def test_history_incremental_private_tail_and_visibility_match(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client:
        create_group(client)
        messages = [send(client, f"public-{i}") for i in range(7)]
        before = get(client, "/api/conversations/conversation")
        for i in range(9):
            send(client, f"private-{i}", private=True)
        assert get(client, "/api/conversations/conversation") == before
        page = get(client, "/api/conversations/conversation/messages/history", limit=3)
        assert [m["message_id"] for m in page["messages"]] == [
            m["message_id"] for m in messages[-3:]
        ]
        poll = page["poll_cursor"]
        added = send(client, "arrived-after-history")
        seen = [m["message_id"] for m in page["messages"]]
        while page["has_older"]:
            page = get(
                client,
                "/api/conversations/conversation/messages/history",
                older_cursor=page["older_cursor"],
                limit=3,
            )
            assert page["poll_cursor"] is None
            seen = [m["message_id"] for m in page["messages"]] + seen
        assert seen == [m["message_id"] for m in messages]
        assert (
            get(client, "/api/conversations/conversation/messages", cursor=poll)["messages"][0][
                "message_id"
            ]
            == added["message_id"]
        )
        assert (
            client.get(
                "/api/conversations/conversation/messages/history",
                params={"player_id": "bob", "older_cursor": poll},
            ).json()["error"]["code"]
            == "invalid_cursor"
        )
        private = get(client, "/api/conversations/conversation/messages/history", "alice", limit=1)[
            "messages"
        ]
        assert private[0]["sender_display"]["display_name"] == "alice"
        system = app.state.application
        with system.database.read() as connection:
            scope = ObservationScope("community", "conversation", ActorRef("player", "bob"), 17)
            expected = {
                m.message_id for m in system.messages.perspective.messages(connection, scope)
            }
            actual = {
                row[0]
                for row in connection.execute(
                    "SELECT m.message_id FROM messages m WHERE m.conversation_id=? AND "
                    + visible_message_sql(),
                    ("conversation", "bob"),
                )
            }
            assert actual == expected


def test_read_markers_membership_retry_and_old_history_reply(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client, TestClient(app, raise_server_exceptions=True) as other:
        create_group(client)
        first = send(client, "first")
        second = send(client, "second")
        send(client, "own", player="bob")
        assert get(client, "/api/conversations/conversation")["unread_count"] == 2
        private = send(client, "private", private=True)
        read_url = "/api/conversations/conversation/read"
        assert (
            client.put(
                read_url, json={"player_id": "bob", "through_message_id": private["message_id"]}
            ).status_code
            == 404
        )
        current = client.put(
            read_url, json={"player_id": "bob", "through_message_id": second["message_id"]}
        ).json()
        older = other.put(
            read_url, json={"player_id": "bob", "through_message_id": first["message_id"]}
        ).json()
        assert older == current and current["unread_count"] == 0
        old_interval = get(client, "/api/conversations/conversation")["self_membership_id"]
        departed = leave(client, "bob", "leave-1", old_interval)
        assert departed.status_code == 200
        gap = send(client, "absent")
        assert (
            get(client, "/api/conversations", membership="past")["items"][0]["conversation_id"]
            == "conversation"
        )
        assert (
            client.get(
                "/api/conversations/conversation/members", params={"player_id": "bob"}
            ).status_code
            == 404
        )
        entered = join(client, "bob", "join-1")
        assert entered.status_code == 200
        new_interval = entered.json()["membership"]["membership_id"]
        assert new_interval != old_interval
        assert leave(client, "bob", "leave-1", old_interval).json() == departed.json()
        assert (
            leave(client, "bob", "leave-2", old_interval).json()["error"]["code"]
            == "membership_interval_conflict"
        )
        assert join(client, "bob", "join-1").json() == entered.json()
        assert (
            leave(client, "bob", "join-1", new_interval).json()["error"]["code"]
            == "idempotency_conflict"
        )
        assert get(client, "/api/conversations/conversation")["self_membership_id"] == new_interval
        assert (
            client.get(
                f"/api/conversations/conversation/messages/{gap['message_id']}",
                params={"player_id": "bob"},
            ).status_code
            == 404
        )
        reply = send(client, "reply-to-old", player="bob", reply=first["message_id"])
        displayed = get(client, f"/api/conversations/conversation/messages/{reply['message_id']}")
        assert displayed["reply_preview"]["message_id"] == first["message_id"]
        public_reply = send(client, "reply-to-private", reply=private["message_id"])
        hidden = get(
            client, f"/api/conversations/conversation/messages/{public_reply['message_id']}"
        )
        assert hidden["reply_preview"] is None
        assert (
            client.get(
                f"/api/conversations/conversation/messages/{private['message_id']}",
                params={"player_id": "bob"},
            ).status_code
            == 404
        )
        system = app.state.application
        system.conversations.archive("community", "conversation")
        assert get(client, "/api/conversations", status="archived")["items"][0]["can_send"] is False
        assert (
            client.post(
                "/api/conversations/conversation/messages",
                json={"player_id": "bob", "client_message_id": "archived", "text": "结束"},
            ).json()["error"]["code"]
            == "conversation_archived"
        )


def test_direct_membership_admin_versions_and_empty_history(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        response = client.post(
            "/api/communities/community/conversations",
            json={
                "player_id": "alice",
                "kind": "direct",
                "conversation_id": "direct",
                "actors": [
                    {"kind": "player", "actor_id": "alice"},
                    {"kind": "character", "actor_id": "first"},
                ],
            },
        )
        assert response.status_code == 201
        empty = get(client, "/api/conversations/direct/messages/history", "alice")
        assert empty["messages"] == [] and empty["poll_cursor"]
        base = "/internal/communities/community/conversations/direct/members"
        version = response.json()["membership_version"]
        for kind, actor in (("player", "alice"), ("character", "first")):
            result = client.delete(
                f"{base}/{kind}/{actor}",
                params={
                    "expected_membership_version": version,
                    "client_operation_id": f"leave-{actor}",
                },
            )
            assert result.status_code == 200, result.text
            version = result.json()["membership_version"]
        assert (
            client.put(
                f"{base}/player/bob",
                json={
                    "expected_membership_version": version,
                    "client_operation_id": "replace-alice",
                },
            ).status_code
            == 409
        )
        entered = client.put(
            f"{base}/player/alice",
            json={"expected_membership_version": version, "client_operation_id": "restore-alice"},
        )
        assert entered.status_code == 200, entered.text
        assert (
            client.put(
                f"{base}/player/alice",
                json={
                    "expected_membership_version": version,
                    "client_operation_id": "restore-alice",
                },
            ).json()
            == entered.json()
        )
        assert (
            client.put(
                f"{base}/character/first",
                json={
                    "expected_membership_version": version,
                    "client_operation_id": "stale-version",
                },
            ).json()["error"]["code"]
            == "membership_version_conflict"
        )
        restored = client.put(
            f"{base}/character/first",
            json={
                "expected_membership_version": entered.json()["membership_version"],
                "client_operation_id": "restore-first",
            },
        )
        assert restored.status_code == 200
        assert len(get(client, "/api/conversations/direct/members", "alice")["items"]) == 2
        assert (
            client.put(
                f"{base}/character/first",
                json={
                    "expected_membership_version": restored.json()["membership_version"],
                    "client_operation_id": "restore-alice",
                },
            ).json()["error"]["code"]
            == "idempotency_conflict"
        )


def test_avatar_resource_load_and_version_binding(tmp_path):
    root = tmp_path / "identity"
    copytree(str(files("echo_commons").joinpath("resources/identity")), root)
    manifest = yaml.safe_load((root / "manifest.yaml").read_text(encoding="utf-8"))
    character = root / manifest["blueprints"]["xiaojin"]["path"]
    document = yaml.safe_load(character.read_text(encoding="utf-8"))
    document["avatar_url"] = "/assets/xiaojin.png"
    character.write_text(yaml.safe_dump(document, allow_unicode=True), encoding="utf-8")
    catalog = load_blueprint_catalog(root)
    assert catalog.blueprint("xiaojin").avatar_url == "/assets/xiaojin.png"
    settings = settings_for(tmp_path, workers=False).model_copy(update={"identity_root": str(root)})
    with TestClient(create_app(settings)) as client:
        create_group(client)
        assert client.get("/api/blueprints").json()[0]["avatar_url"] == "/assets/xiaojin.png"
        assert (
            get(client, "/api/communities/community/characters", "alice")[0]["avatar_url"]
            == "/assets/xiaojin.png"
        )
        identity = client.app.state.application.community_query.identity
        identity.catalog = replace(
            catalog,
            blueprints={"xiaojin": replace(catalog.blueprint("xiaojin"), content_version="0.2.0")},
        )
        with (
            client.app.state.application.database.read() as connection,
            pytest.raises(ConflictError),
        ):
            identity.display(connection, "community", ActorRef("character", "first"))


def test_version_three_migration_preserves_records(tmp_path):
    sql = tmp_path / "version3"
    sql.mkdir()
    for source in files("echo_commons").joinpath("infrastructure/database/sql").iterdir():
        if source.name.endswith(".sql") and int(source.name[:4]) <= 3:
            (sql / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    database = Database(tmp_path / "old.sqlite3")
    assert initialize(database, sql_directory=sql) == 3
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO players VALUES (?,?,?)",
            ("original", "原玩家", "2026-10-04T00:00:00+00:00"),
        )
    assert initialize(database) == initialize(database) == 4
    with database.read() as connection:
        assert (
            connection.execute(
                "SELECT display_name FROM players WHERE player_id='original'"
            ).fetchone()[0]
            == "原玩家"
        )
        assert (
            connection.execute("SELECT COUNT(*) FROM conversation_read_positions").fetchone()[0]
            == 0
        )
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_concurrent_member_retry_uses_one_real_transaction_result(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        assert leave(client, "bob", "before-concurrent-join").status_code == 200
        request = MembershipOperation(
            community_id="community",
            conversation_id="conversation",
            actor=ActorRef("player", "bob"),
            player_id="bob",
            action="join",
        )
        service = client.app.state.application.conversations
        with ThreadPoolExecutor(max_workers=2) as executor:
            results = list(
                executor.map(
                    lambda _: service.apply_membership(request, "concurrent-join"), range(2)
                )
            )
        assert results[0] == results[1]
        with client.app.state.application.database.read() as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM conversation_memberships "
                    "WHERE conversation_id='conversation' AND actor_id='bob' "
                    "AND left_at_utc IS NULL"
                ).fetchone()[0]
                == 1
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM conversation_membership_operations "
                    "WHERE client_operation_id='concurrent-join'"
                ).fetchone()[0]
                == 1
            )
