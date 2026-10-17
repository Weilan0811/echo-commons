import pytest
from fastapi.testclient import TestClient
from support.application import settings_for
from support.games import create, move, operation, prepare_players, running_game, session

from echo_commons.app.main import create_app


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        prepare_players(client)
        yield client


def path(created):
    conversation_id = created["conversation"]["conversation_id"]
    return f"/internal/communities/community/conversations/{conversation_id}/game"


def test_inspection_contains_actual_state_and_both_receipt_types(client):
    created, _, _ = running_game(client)
    identity = created["game_id"]
    action, command = move(client, identity, "alice", 7, 7)
    before = session(client, identity)
    inspection = client.get(path(created))
    assert inspection.status_code == 200, inspection.text
    document = inspection.json()
    assert document["game"]["game_id"] == identity
    assert document["game"]["state"]["stones"] == [{"x": 7, "y": 7, "seat_id": "black"}]
    assert {item["participant_ref"] for item in document["participations"]} == {
        "player:alice",
        "player:bob",
    }
    actions = client.get(path(created) + "/records", params={"kind": "actions"}).json()
    assert len(actions["items"]) == 1
    assert actions["items"][0]["document"] == action
    assert actions["items"][0]["command"]["action"] == command["action"]
    operation(
        client,
        identity,
        "resign",
        player="bob",
        participation_id=before["game"]["seats"][1]["occupant"]["participation_id"],
    )
    finished = session(client, identity)
    operation(
        client,
        identity,
        "end",
        expected_conversation_version=finished["conversation"]["state_version"],
    )
    records = client.get(path(created) + "/records", params={"kind": "operations"})
    assert records.status_code == 200, records.text
    by_kind = {item["document"]["operation"]: item for item in records.json()["items"]}
    assert set(by_kind) == {"create", "join", "start", "resign", "end"}
    assert by_kind["create"]["position"] == 1
    assert by_kind["start"]["document"]["game_receipt"]["result"]["type"] == "started"
    assert by_kind["end"]["document"]["game_receipt"] is None
    assert by_kind["end"]["position"] == finished["game"]["state_version"]
    assert session(client, identity)["game"]["state_version"] == finished["game"]["state_version"]


@pytest.mark.parametrize("kind", ["events", "actions", "operations"])
def test_game_record_pagination_binds_kind_and_conversation(client, kind):
    first, _, _ = running_game(client)
    move(client, first["game_id"], "alice", 7, 7)
    move(client, first["game_id"], "bob", 7, 8)
    second, _ = create(client, request_id="another-game")
    response = client.get(path(first) + "/records", params={"kind": kind, "limit": 1})
    assert response.status_code == 200, response.text
    page = response.json()
    assert page["has_more"] is True
    following = client.get(
        path(first) + "/records", params={"kind": kind, "cursor": page["cursor"], "limit": 1}
    ).json()
    assert following["items"][0]["position"] > page["items"][0]["position"]
    assert (
        client.get(
            path(first) + "/records",
            params={"kind": "actions" if kind == "events" else "events", "cursor": page["cursor"]},
        ).status_code
        == 400
    )
    assert (
        client.get(
            path(second) + "/records", params={"kind": kind, "cursor": page["cursor"]}
        ).status_code
        == 400
    )
    assert client.get(path(first).replace("/community/", "/missing/", 1)).status_code == 404
    assert (
        client.get(
            path(first).replace("/community/", "/missing/", 1) + "/records",
            params={"kind": "events"},
        ).status_code
        == 404
    )
    assert client.get(path(first) + "/records", params={"kind": "unknown"}).status_code == 422


def test_management_reads_waiting_game_without_creating_state_or_opportunities(client):
    created, _ = create(client)
    before = session(client, created["game_id"])
    inspection = client.get(path(created)).json()
    assert inspection["game"]["state"] is None
    assert client.get(path(created) + "/records", params={"kind": "actions"}).json()["items"] == []
    assert session(client, created["game_id"]) == before
    assert (
        client.get(
            f"/api/games/{created['game_id']}/view", params={"player_id": "cara"}
        ).status_code
        == 404
    )
