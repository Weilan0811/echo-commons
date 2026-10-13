import time

import pytest
from fastapi.testclient import TestClient
from historical_messages import historical_message, historical_receipt
from test_application_lifecycle import settings_for

from echo_commons.app.main import create_app
from echo_commons.modules.characters.domain.authoring import AuthoringContent
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog
from echo_commons.shared.actors import ActorRef


@pytest.mark.model
def test_http_group_runs_real_models_and_returns_completed_turn(tmp_path):
    app = create_app(settings_for(tmp_path, workers=True))
    with TestClient(app) as client:
        create_group(client)
        receipt = client.post(
            "/api/conversations/conversation/messages",
            json={
                "player_id": "alice",
                "client_message_id": "greeting",
                "text": "两位小槿，请各自用一句话说说今天想一起做什么。",
            },
        )
        assert receipt.status_code == 202
        deadline = time.monotonic() + 120
        while True:
            turns = client.get(
                "/api/conversations/conversation/turns", params={"player_id": "alice"}
            )
            assert turns.status_code == 200
            if turns.json() and turns.json()[0]["chain_status"] == "completed":
                break
            assert time.monotonic() < deadline, turns.json()
            time.sleep(0.1)
        page = client.get("/api/conversations/conversation/messages", params={"player_id": "bob"})
        assert page.status_code == 200
        messages = page.json()["messages"]
        replies = [message for message in messages if message["sender"]["kind"] == "character"]
        assert {message["sender"]["actor_id"] for message in replies} == {"first", "second"}
        assert all(message["text"] and "thought" not in message for message in replies)
        assert all(
            message["source_turn_id"] in {turn["social_turn_id"] for turn in turns.json()}
            for message in replies
        )
        assert (
            client.post(
                "/api/communities/community/conversations",
                json={
                    "player_id": "alice",
                    "conversation_id": "direct",
                    "kind": "direct",
                    "actors": [
                        {"kind": "player", "actor_id": "alice"},
                        {"kind": "character", "actor_id": "first"},
                    ],
                },
            ).status_code
            == 201
        )
        private = client.post(
            "/api/conversations/direct/messages",
            json={
                "player_id": "alice",
                "client_message_id": "private-greeting",
                "text": "请用一句话确认收到晚餐暗号草莓417。",
            },
        )
        assert private.status_code == 202
        deadline = time.monotonic() + 120
        while True:
            own_turns = client.get(
                "/api/conversations/direct/turns", params={"player_id": "alice"}
            ).json()
            if len(own_turns) == 1 and own_turns[-1]["status"] == "completed":
                break
            assert time.monotonic() < deadline, own_turns
            time.sleep(0.1)
        assert len(
            client.get("/api/conversations/conversation/turns", params={"player_id": "bob"}).json()
        ) == len(turns.json())
        own_messages = client.get(
            "/api/conversations/direct/messages", params={"player_id": "alice"}
        ).json()["messages"]
        private_replies = [
            message
            for message in own_messages
            if message["source_turn_id"] == own_turns[-1]["social_turn_id"]
        ]
        assert len(private_replies) == 1
        assert private_replies[0]["sender"]["actor_id"] == "first"
        other_messages = client.get(
            "/api/conversations/conversation/messages", params={"player_id": "bob"}
        ).json()["messages"]
        assert private.json()["message_id"] not in {item["message_id"] for item in other_messages}
        assert private_replies[0]["message_id"] not in {
            item["message_id"] for item in other_messages
        }
        assert (
            client.get(
                "/api/conversations/direct/messages", params={"player_id": "bob"}
            ).status_code
            == 404
        )
        assert (
            client.get("/api/conversations/direct/turns", params={"player_id": "bob"}).status_code
            == 404
        )
        assert client.get("/health/ready").status_code == 200
        with app.state.application.database.read() as connection:
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        clients = tuple(app.state.application.gateway._clients.values())
    assert clients and all(model_client.is_closed() for model_client in clients)
    assert app.state.application.supervisor._tasks == []


def test_new_community_http_uses_real_services_and_strict_body(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client:
        player = client.post("/api/players", json={"display_name": "测试玩家"})
        assert player.status_code == 201
        player_id = player.json()["player_id"]
        community = client.post(
            "/api/communities",
            json={"player_id": player_id, "name": "测试社群", "timezone": "Asia/Shanghai"},
        )
        assert community.status_code == 201
        community_id = community.json()["community_id"]
        url = f"/api/communities/{community_id}/players/{player_id}"
        assert client.put(url).status_code == 200
        assert client.put(url).status_code == 200
        assert client.put(f"/api/communities/missing/players/{player_id}").status_code == 404
        assert client.post("/api/players", json={"displayName": "旧字段"}).status_code == 422
        assert (
            client.post(
                "/api/communities",
                json={"player_id": player_id, "name": "错误时区", "timezone": "missing/timezone"},
            ).status_code
            == 400
        )
        assert client.post("/message/send", json={}).status_code == 404
        assert client.get("/health/live").json()["version"] == "0.1.0"
        with app.state.application.database.read() as connection:
            assert connection.execute("SELECT COUNT(*) FROM community_members").fetchone()[0] == 1
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_new_messages_use_conversation_members_and_isolate_direct_chat(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client:
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
        assert response.status_code == 201, response.text
        public = client.post(
            "/api/conversations/conversation/messages",
            json={
                "player_id": "alice",
                "client_message_id": "public",
                "text": "大家一起讨论",
                "mentions": [{"kind": "character", "actor_id": "first"}],
            },
        )
        private = client.post(
            "/api/conversations/direct/messages",
            json={"player_id": "alice", "client_message_id": "direct", "text": "晚餐暗号草莓417"},
        )
        assert public.status_code == private.status_code == 202
        group = client.get(
            "/api/conversations/conversation/messages", params={"player_id": "bob"}
        ).json()["messages"]
        assert [message["message_id"] for message in group] == [public.json()["message_id"]]
        own = client.get(
            "/api/conversations/direct/messages", params={"player_id": "alice"}
        ).json()["messages"]
        assert own[0]["visibility"] == "conversation" and own[0]["recipients"] == []
        assert (
            client.get(
                "/api/conversations/direct/messages", params={"player_id": "bob"}
            ).status_code
            == 404
        )
        assert (
            client.post(
                "/api/conversations/conversation/messages",
                json={
                    "player_id": "alice",
                    "client_message_id": "cross-reply",
                    "text": "引用私聊",
                    "reply_to_message_id": private.json()["message_id"],
                },
            ).status_code
            == 404
        )
        with app.state.application.database.read() as connection:
            counts = dict(
                connection.execute(
                    "SELECT message_id, COUNT(*) FROM message_recipients GROUP BY message_id"
                ).fetchall()
            )
        assert counts == {public.json()["message_id"]: 4, private.json()["message_id"]: 2}


def create_group(client, *, memory_mode="full"):
    actors = []
    for player in ("alice", "bob"):
        response = client.post("/api/players", json={"player_id": player, "display_name": player})
        assert response.status_code == 201
        actors.append({"kind": "player", "actor_id": player})
    community = client.post(
        "/api/communities",
        json={"player_id": "alice", "community_id": "community", "name": "群聊", "timezone": "UTC"},
    )
    assert community.status_code == 201
    assert (
        client.patch(
            "/api/communities/community/status",
            json={"player_id": "alice", "status": "active", "expected_version": 0},
        ).status_code
        == 200
    )
    assert client.put("/api/communities/community/players/bob").status_code == 200
    blueprints = client.get("/api/blueprints")
    assert blueprints.status_code == 200
    assert blueprints.json()[0]["content_version"] == "0.1.0"
    blueprint_id = "xiaojin"
    if memory_mode == "full":
        from test_character_authoring import confirm, create_draft

        template = load_blueprint_catalog().blueprint("xiaojin")
        content = AuthoringContent(
            display_name=template.display_name,
            description="基础人物资料。",
            profile=template.profile.content,
            voice=template.voice.content,
            relational_dynamics=template.relational_dynamics.content,
        )
        draft, _ = create_draft(
            client,
            name=template.display_name,
            **content.model_dump(exclude={"display_name"}, mode="json"),
        )
        blueprint, _ = confirm(client, draft)
        blueprint_id = blueprint["blueprint_id"]
    for character in ("first", "second"):
        response = client.post(
            "/api/communities/community/characters",
            json={
                "player_id": "alice",
                "blueprint_id": blueprint_id,
                "character_id": character,
                "memory_mode": memory_mode,
            },
        )
        assert response.status_code == 201
        assert "memory" not in response.json() and "state_entries" not in response.json()
        actors.append({"kind": "character", "actor_id": character})
    response = client.post(
        "/api/communities/community/conversations",
        json={
            "player_id": "alice",
            "kind": "group",
            "actors": actors,
            "conversation_id": "conversation",
        },
    )
    assert response.status_code == 201
    assert "next_sequence" not in response.json()


def test_http_messages_keep_player_visibility_cursor_and_membership(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        assert (
            len(
                client.get(
                    "/api/communities/community/characters", params={"player_id": "alice"}
                ).json()
            )
            == 2
        )
        assert (
            len(client.get("/api/conversations", params={"player_id": "alice"}).json()["items"])
            == 1
        )
        url = "/api/conversations/conversation/messages"
        private = {
            "player_id": "alice",
            "client_message_id": "private",
            "text": "私有暗号",
            "visibility": "recipients",
            "recipients": [{"kind": "character", "actor_id": "first"}],
        }
        assert client.post(url, json=private).status_code == 422
        for field in ("visibility", "recipients"):
            body = {
                key: value
                for key, value in private.items()
                if key not in ("visibility", "recipients")
            }
            assert client.post(url, json={**body, field: private[field]}).status_code == 422
        historical_receipt(client, "private", "私有暗号")
        body = {
            key: value for key, value in private.items() if key not in ("visibility", "recipients")
        }
        collision = client.post(url, json=body)
        assert collision.status_code == 409
        assert "idempotency_conflict" in collision.text
        bob = client.get(url, params={"player_id": "bob"}).json()
        assert bob["messages"] == []
        public = client.post(
            url,
            json={
                "player_id": "alice",
                "client_message_id": "public",
                "text": "公共消息",
            },
        )
        assert public.status_code == 202
        page = client.get(url, params={"player_id": "bob", "cursor": bob["cursor"]}).json()
        assert [message["text"] for message in page["messages"]] == ["公共消息"]
        assert "result_id" not in page["messages"][0]
        assert "audience" not in page["messages"][0]
        own = client.get(url, params={"player_id": "alice"}).json()
        assert len(own["messages"]) == 2
        assert (
            client.get(url, params={"player_id": "bob", "cursor": own["cursor"]}).status_code == 400
        )
        assert client.get(url, params={"player_id": "outsider"}).status_code == 404
        member = "/api/conversations/conversation/membership"
        previous = client.get("/api/conversations/conversation", params={"player_id": "bob"}).json()
        assert (
            client.delete(
                member,
                params={
                    "player_id": "bob",
                    "expected_membership_id": previous["self_membership_id"],
                    "client_operation_id": "leave-bob",
                },
            ).status_code
            == 200
        )
        current = client.put(
            member, json={"player_id": "bob", "client_operation_id": "join-bob"}
        ).json()
        assert current["membership"]["membership_id"] != previous["self_membership_id"]
        assert client.post(url, json={**private, "chips": []}).status_code == 422


def test_http_turn_visibility_and_internal_context_scope(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client:
        create_group(client)
        assert client.get("/health/ready").status_code == 200
        historical_message(
            app.state.application,
            "私有讨论",
            client="private-turn",
            recipients=(ActorRef("character", "first"),),
        )
        assert len(app.state.application.planner.plan()) == 1
        url = "/api/conversations/conversation/turns"
        assert client.get(url, params={"player_id": "bob"}).json() == []
        own = client.get(url, params={"player_id": "alice"})
        assert own.status_code == 200 and len(own.json()) == 1
        turn = own.json()[0]
        assert "audience" not in turn and "observation_max_sequence" not in turn
        assert "snapshot" not in str(turn) and "thought" not in str(turn)
        with app.state.application.database.read() as connection:
            task = connection.execute(
                "SELECT task_id FROM conversation_tasks WHERE character_id = 'first'"
            ).fetchone()[0]
        context = f"/internal/characters/first/tasks/{task}/context"
        assert client.get(context, params={"community_id": "community"}).status_code == 200
        assert client.get(context, params={"community_id": "other"}).status_code == 404
        assert (
            client.get(
                f"/internal/characters/second/tasks/{task}/context",
                params={"community_id": "community"},
            ).status_code
            == 404
        )
        assert client.get(url, params={"player_id": "outside"}).status_code == 404
