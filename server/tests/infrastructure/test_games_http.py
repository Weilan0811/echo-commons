from concurrent.futures import ThreadPoolExecutor

import pytest
from fastapi.testclient import TestClient
from support.application import settings_for
from support.games import create, move, operation, prepare_players, running_game, session, view

from echo_commons.app.main import create_app


@pytest.fixture
def client(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"model_secrets_path": str(tmp_path / "missing-credentials.toml")}
    )
    with TestClient(create_app(settings)) as client:
        prepare_players(client)
        yield client


def test_registered_directory_room_capabilities_and_enter_without_join(client):
    directory = client.get("/api/game-types")
    assert directory.status_code == 200
    assert [item["game_type"] for item in directory.json()["items"]] == [
        "aeroplane",
        "gomoku",
        "kingdomino",
    ]
    rules = client.get("/api/game-types/gomoku")
    assert rules.status_code == 200 and rules.json()["rulesets"][0]["config"] == {}
    assert client.get("/api/game-types/chess").status_code == 404
    created, body = create(client)
    identity = created["game_id"]
    assert client.post("/api/games", json=body).json() == created
    before = session(client, identity)
    assert before["game"]["config"] == {} and before["game"]["status"] == "waiting"
    assert before["capabilities"] == {
        "can_join": False,
        "can_leave": True,
        "can_start": False,
        "can_resign": False,
        "can_cancel": True,
        "can_end": True,
        "can_invite": True,
        "removable_participation_ids": [],
        "start_blocked_reason": None,
    }
    bob = session(client, identity, "bob")
    assert bob["self_participation_id"] is None and bob["capabilities"]["can_join"]
    assert session(client, identity) == before
    assert (
        client.get(f"/api/games/{identity}/view", params={"player_id": "alice"}).status_code == 409
    )
    assert client.get(f"/api/games/{identity}/view", params={"player_id": "bob"}).status_code == 404


def test_creation_requires_explicit_game_identity_and_rejects_unusable_config(client):
    assert (
        client.post(
            "/api/games",
            json={"player_id": "alice", "community_id": "community", "request_id": "missing-type"},
        ).status_code
        == 422
    )
    rejected = client.post(
        "/api/games",
        json={
            "player_id": "alice",
            "community_id": "community",
            "request_id": "bad-config",
            "game_type": "gomoku",
            "ruleset_id": "gomoku.freestyle",
            "ruleset_version": 1,
            "initial_seat_id": "black",
            "config": {"board_size": 19},
        },
    )
    assert rejected.status_code == 400 and rejected.json()["error"]["code"] == "invalid_command"
    assert (
        client.get("/api/games", params={"community_id": "community", "player_id": "alice"}).json()[
            "items"
        ]
        == []
    )


def test_real_full_game_action_receipts_events_chat_and_end(client):
    created, _, _ = running_game(client)
    identity = created["game_id"]
    first_view = view(client, identity)
    assert len(first_view["opportunities"][0]["legal_actions"]) == 225
    decision = client.get(
        f"/api/games/{identity}/decision-input",
        params={
            "player_id": "alice",
            "opportunity_id": first_view["opportunities"][0]["opportunity_id"],
        },
    )
    assert decision.status_code == 200 and decision.json()["view"] == first_view
    first, first_body = move(client, identity, "alice", 0, 0, request_id="first-move")
    assert client.post(f"/api/games/{identity}/actions", json=first_body).json() == first
    for x in range(4):
        move(client, identity, "bob", x, 1)
        move(client, identity, "alice", x + 1, 0)
    finished = session(client, identity)
    assert finished["game"]["result"] == {"reason": "line", "winner_seat_id": "black"}
    assert finished["game"]["state_version"] == 12
    assert not finished["capabilities"]["can_resign"]
    assert view(client, identity)["opportunities"] == []
    receipt = client.get(f"/api/games/{identity}/actions/first-move", params={"player_id": "alice"})
    assert receipt.status_code == 200 and receipt.json() == first
    assert (
        client.get(
            f"/api/games/{identity}/actions/first-move", params={"player_id": "bob"}
        ).status_code
        == 404
    )
    page = client.get(f"/api/games/{identity}/events", params={"player_id": "alice", "limit": 200})
    assert page.status_code == 200, page.text
    items = page.json()["items"]
    assert [item["type"] for item in items].count("stone_placed") == 9
    assert items[-1]["data"]["result"] == {"reason": "line", "winner_seat_id": "black"}
    chat = client.post(
        f"/api/conversations/{created['conversation']['conversation_id']}/messages",
        json={
            "player_id": "bob",
            "client_message_id": "after-game",
            "text": "再来一局吧",
        },
    )
    assert chat.status_code == 202
    ended, end_body = operation(
        client, identity, "end", expected_conversation_version=1, request_id="end"
    )
    assert ended["game_receipt"] is None and ended["conversation"]["status"] == "archived"
    assert client.post(f"/api/games/{identity}/end", json=end_body).json() == ended
    assert client.post(f"/api/games/{identity}/actions", json=first_body).json() == first
    assert (
        client.get(f"/api/games/{identity}/operations/end", params={"player_id": "alice"}).json()
        == ended
    )
    assert session(client, identity)["game"] == finished["game"]


def test_resign_and_cancel_have_actual_outcomes_and_keep_original_results(client):
    created, _, _ = running_game(client)
    identity = created["game_id"]
    pid = session(client, identity, "bob")["self_participation_id"]
    resigned, body = operation(client, identity, "resign", player="bob", participation_id=pid)
    assert resigned["game_receipt"]["result"]["result"] == {
        "reason": "resignation",
        "winner_seat_id": "black",
    }
    operation(client, identity, "end", expected_conversation_version=1)
    assert client.post(f"/api/games/{identity}/resign", json=body).json() == resigned
    other, _ = create(client, request_id="other-create")
    cancelled, cancel_body = operation(
        client, other["game_id"], "cancel", reason="players_cancelled"
    )
    assert cancelled["game_receipt"]["status_after"] == "cancelled"
    assert cancelled["conversation"]["status"] == "active"
    response = client.post(
        f"/api/conversations/{other['conversation']['conversation_id']}/messages",
        json={
            "player_id": "alice",
            "client_message_id": "cancelled-chat",
            "text": "取消之后的新消息",
        },
    )
    assert response.status_code == 409
    operation(client, other["game_id"], "end", expected_conversation_version=1)
    assert (
        client.post(f"/api/games/{other['game_id']}/cancel", json=cancel_body).json() == cancelled
    )


def test_resign_capability_follows_the_game_declaration(client):
    created, _, _ = running_game(client)
    assert session(client, created["game_id"])["capabilities"]["can_resign"] is True

    for game_type, ruleset_id, seats in (
        ("aeroplane", "aeroplane.traditional", ("red", "blue")),
        ("kingdomino", "kingdomino.classic", ("pink", "yellow")),
    ):
        response = client.post(
            "/api/games",
            json={
                "player_id": "alice",
                "community_id": "community",
                "request_id": f"{game_type}-create",
                "game_type": game_type,
                "ruleset_id": ruleset_id,
                "ruleset_version": 1,
                "initial_seat_id": seats[0],
            },
        )
        assert response.status_code == 201, response.text
        identity = response.json()["game_id"]
        operation(client, identity, "participants", player="bob", seat_id=seats[1])
        operation(client, identity, "start")
        running = session(client, identity)
        assert running["game"]["status"] == "running"
        assert running["capabilities"]["can_resign"] is False

        refused = client.post(
            f"/api/games/{identity}/resign",
            json={
                "player_id": "alice",
                "request_id": f"{game_type}-resign",
                "expected_state_version": running["game"]["state_version"],
                "participation_id": running["self_participation_id"],
            },
        )
        assert refused.status_code == 409, refused.text
        assert refused.json()["error"]["code"] == "operation_not_supported"


def test_leave_rejoin_original_operations_and_participation_bound_cursors(client):
    created, _ = create(client)
    identity = created["game_id"]
    joined, _ = operation(client, identity, "participants", player="bob", seat_id="white")
    old_pid = joined["game_receipt"]["result"]["participation"]["participation_id"]
    events = client.get(
        f"/api/games/{identity}/events", params={"player_id": "bob", "limit": 1}
    ).json()
    assert events["items"] == [] and events["has_more"]
    left, body = operation(
        client, identity, "leave", player="bob", participation_id=old_pid, request_id="leave"
    )
    operation(client, identity, "participants", player="bob", seat_id="white")
    assert session(client, identity, "bob")["self_participation_id"] != old_pid
    assert client.post(f"/api/games/{identity}/leave", json=body).json() == left
    assert (
        client.get(f"/api/games/{identity}/operations/leave", params={"player_id": "bob"}).json()
        == left
    )
    assert (
        client.get(
            f"/api/games/{identity}/events", params={"player_id": "bob", "cursor": events["cursor"]}
        ).status_code
        == 400
    )
    assert (
        client.get(
            f"/api/games/{identity}/events",
            params={
                "player_id": "bob",
                "cursor": events["cursor"],
                "participation_id": old_pid,
            },
        ).status_code
        == 200
    )
    own_pid = session(client, identity)["self_participation_id"]
    assert (
        client.get(
            f"/api/games/{identity}/events",
            params={"player_id": "bob", "participation_id": own_pid},
        ).status_code
        == 404
    )
    assert (
        client.get(
            f"/api/games/{identity}/events",
            params={"player_id": "alice", "cursor": events["cursor"]},
        ).status_code
        == 400
    )


def test_list_filters_pagination_cursor_scope_and_unrelated_community(client):
    identities = {create(client, request_id=f"create-{index}")[0]["game_id"] for index in range(4)}
    page = client.get(
        "/api/games",
        params={"community_id": "community", "player_id": "bob", "status": "waiting", "limit": 2},
    )
    assert page.status_code == 200, page.text
    first = page.json()
    assert first["has_more"] and len(first["items"]) == 2
    second = client.get(
        "/api/games",
        params={
            "community_id": "community",
            "player_id": "bob",
            "status": "waiting",
            "limit": 2,
            "cursor": first["cursor"],
        },
    ).json()
    assert not second["has_more"] and second["cursor"] is None
    assert {item["game"]["game_id"] for item in first["items"] + second["items"]} == identities
    for changed in ({"player_id": "alice"}, {"status": "running"}, {"game_type": "gomoku"}):
        response = client.get(
            "/api/games",
            params={
                "community_id": "community",
                "player_id": "bob",
                "status": "waiting",
                "cursor": first["cursor"],
                **changed,
            },
        )
        assert response.status_code == 400
    assert (
        client.get(
            "/api/games",
            params={"community_id": "community", "player_id": "bob", "game_type": "aeroplane"},
        ).json()["items"]
        == []
    )
    assert (
        client.post(
            "/api/communities",
            json={"player_id": "alice", "community_id": "other", "name": "其他社群"},
        ).status_code
        == 201
    )
    assert (
        client.get("/api/games", params={"community_id": "other", "player_id": "alice"}).json()[
            "items"
        ]
        == []
    )
    assert (
        client.get("/api/games", params={"community_id": "other", "player_id": "bob"}).status_code
        == 404
    )


def test_real_failures_return_distinct_status_codes_and_do_not_modify_game(client):
    created, _, _ = running_game(client)
    identity = created["game_id"]
    assert client.get(f"/api/games/{identity}", params={"player_id": "outside"}).status_code == 404
    assert client.get("/api/games/unknown", params={"player_id": "alice"}).status_code == 404
    response = client.post(
        f"/api/games/{identity}/cancel",
        json={
            "player_id": "bob",
            "request_id": "forbidden",
            "expected_state_version": 3,
            "reason": "other_player",
        },
    )
    assert response.status_code == 403 and response.json()["error"]["code"] == "operation_forbidden"
    before = view(client, identity)
    opportunity = before["opportunities"][0]["opportunity_id"]
    base = {
        "player_id": "alice",
        "request_id": "invalid",
        "opportunity_id": opportunity,
        "expected_state_version": 3,
        "action": {"type": "place_stone", "x": 7, "y": 7},
    }
    for change, status, code in (
        ({"player_id": "bob"}, 409, "not_current_actor"),
        ({"expected_state_version": 2}, 409, "state_version_conflict"),
        ({"opportunity_id": "old-opportunity"}, 409, "opportunity_expired"),
    ):
        response = client.post(f"/api/games/{identity}/actions", json={**base, **change})
        assert response.status_code == status and response.json()["error"]["code"] == code
    for action in (
        {"type": "place_stone", "x": 15, "y": 0},
        {"type": "place_stone", "x": True, "y": 0},
        {"type": "roll_dice"},
    ):
        rejected = client.post(f"/api/games/{identity}/actions", json={**base, "action": action})
        assert rejected.status_code == 400
        assert rejected.json()["error"]["code"] == "invalid_command"
    assert (
        client.post(f"/api/games/{identity}/actions", json={**base, "seat_id": "white"}).status_code
        == 422
    )
    assert view(client, identity) == before
    receipt, body = move(client, identity, "alice", 7, 7)
    changed = client.post(
        f"/api/games/{identity}/actions",
        json={**body, "action": {"type": "place_stone", "x": 0, "y": 0}},
    )
    assert changed.status_code == 409 and changed.json()["error"]["code"] == "idempotency_conflict"
    bob = view(client, identity, "bob")
    occupied = {
        **base,
        "player_id": "bob",
        "expected_state_version": bob["state_version"],
        "opportunity_id": bob["opportunities"][0]["opportunity_id"],
    }
    response = client.post(f"/api/games/{identity}/actions", json=occupied)
    assert response.status_code == 400 and response.json()["error"]["code"] == "illegal_action"
    assert session(client, identity)["game"]["state_version"] == receipt["state_version_after"]


def test_parallel_joiners_compete_for_one_real_seat(client):
    created, _ = create(client)
    identity = created["game_id"]

    def compete(player):
        return client.post(
            f"/api/games/{identity}/participants",
            json={
                "player_id": player,
                "request_id": player,
                "expected_state_version": 1,
                "seat_id": "white",
                "participant": {"kind": "player"},
            },
        )

    with ThreadPoolExecutor(max_workers=2) as pool:
        responses = list(pool.map(compete, ("bob", "cara")))
    assert sorted(response.status_code for response in responses) == [200, 409]
    assert session(client, identity)["game"]["state_version"] == 2


def test_openapi_exposes_loose_game_inputs_and_typed_event_map(client):
    response = client.get("/openapi.json")
    assert response.status_code == 200
    document = response.json()
    schemas = document["components"]["schemas"]
    assert schemas["CreateGameRequest"]["properties"]["config"]["$ref"].endswith(
        "/UnvalidatedPayload"
    )
    assert schemas["SubmitGameActionRequest"]["properties"]["action"]["$ref"].endswith(
        "/UnvalidatedPayload"
    )
    payload = schemas["UnvalidatedPayload"]
    assert payload["type"] == "object" and payload["additionalProperties"] is True
    assert schemas["GameTypeResponse"]["properties"]["game_type"]["type"] == "string"
    assert schemas["GameTypeResponse"]["properties"]["rulesets"]["items"]["$ref"].endswith(
        "/RulesetResponse"
    )
    assert schemas["EventPayloadMap"]["properties"]["game.changed"]["$ref"].endswith(
        "/GameChangedData"
    )
    assert set(schemas["GameChangedData"]["properties"]) == {
        "community_id",
        "game_id",
        "state_version",
    }
    assert "/api/games/{game_id}/decision-input" in document["paths"]
    assert "403" in document["paths"]["/api/games/{game_id}/cancel"]["post"]["responses"]
