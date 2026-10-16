from uuid import uuid4


def prepare_players(client):
    for player in ("alice", "bob", "cara", "outside"):
        response = client.post("/api/players", json={"player_id": player, "display_name": player})
        assert response.status_code == 201, response.text
    response = client.post(
        "/api/communities",
        json={
            "player_id": "alice",
            "community_id": "community",
            "name": "游戏社群",
            "timezone": "UTC",
        },
    )
    assert response.status_code == 201, response.text
    for player in ("bob", "cara"):
        assert client.put(f"/api/communities/community/players/{player}").status_code == 200


def create(client, *, request_id="create", community_id="community", player="alice"):
    body = {"player_id": player, "community_id": community_id, "request_id": request_id}
    response = client.post("/api/games", json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


def session(client, identity, player="alice"):
    response = client.get(f"/api/games/{identity}", params={"player_id": player})
    assert response.status_code == 200, response.text
    return response.json()


def operation(client, identity, action, *, player="alice", version=None, request_id=None, **fields):
    if version is None:
        version = session(client, identity, player)["game"]["state_version"]
    body = {
        "player_id": player,
        "request_id": request_id or uuid4().hex,
        "expected_state_version": version,
        **fields,
    }
    response = client.post(f"/api/games/{identity}/{action}", json=body)
    assert response.status_code == 200, response.text
    return response.json(), body


def running_game(client):
    created, _ = create(client)
    identity = created["game_id"]
    joined, _ = operation(
        client, identity, "participants", player="bob", seat_id="white", request_id="join"
    )
    started, _ = operation(client, identity, "start", request_id="start")
    return created, joined, started


def view(client, identity, player="alice"):
    response = client.get(f"/api/games/{identity}/view", params={"player_id": player})
    assert response.status_code == 200, response.text
    return response.json()


def move(client, identity, player, x, y, request_id=None):
    before = view(client, identity, player)
    opportunity = before["opportunities"][0]
    body = {
        "player_id": player,
        "request_id": request_id or uuid4().hex,
        "opportunity_id": opportunity["opportunity_id"],
        "expected_state_version": opportunity["expected_state_version"],
        "action": {"type": "place_stone", "x": x, "y": y},
    }
    response = client.post(f"/api/games/{identity}/actions", json=body)
    assert response.status_code == 200, response.text
    return response.json(), body
