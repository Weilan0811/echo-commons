import json

import pytest
from fastapi.testclient import TestClient
from support.application import settings_for
from support.games import create, move, operation, session
from support.http import create_group

from echo_commons.app.main import create_app
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client, memory_mode="simple")
        yield client


def invite(client, identity, *, character="first", **fields):
    return operation(
        client,
        identity,
        "participants",
        seat_id="white",
        participant={"kind": "character", "character_id": character},
        **fields,
    )


def test_character_join_withdraw_rejoin_and_request_recovery(client):
    app = client.app.state.application
    created, _ = create(client)
    identity = created["game_id"]
    candidates = client.get(
        f"/api/games/{identity}/participant-candidates",
        params={"player_id": "alice", "limit": 1},
    ).json()
    assert candidates["has_more"] and candidates["items"][0]["eligible"]
    following = client.get(
        f"/api/games/{identity}/participant-candidates",
        params={"player_id": "alice", "cursor": candidates["cursor"], "limit": 1},
    ).json()
    assert following["items"][0]["character_id"] != candidates["items"][0]["character_id"]
    joined, original = invite(client, identity, request_id="invite-first")
    participation = joined["game_receipt"]["result"]["participation"]
    assert participation["participant_ref"] == "character:first"
    assert participation["invited_by_ref"] == "player:alice"
    assert joined["memberships"][0]["actor"] == {"kind": "character", "actor_id": "first"}
    before = session(client, identity)
    assert before["capabilities"]["removable_participation_ids"] == [
        participation["participation_id"]
    ]
    observed = app.game_observations.observe("community", "first", identity)
    assert observed.view is None
    assert observed.context.access.participation_id == participation["participation_id"]
    old_ids = {event.event_id for event in observed.events.items}
    app.character_state.set_availability("community", "first", "offline", expected_version=0)
    assert client.post(f"/api/games/{identity}/participants", json=original).json() == joined
    withdrawn, leave = operation(
        client,
        identity,
        "leave",
        participation_id=participation["participation_id"],
    )
    assert withdrawn["memberships"][0]["actor"]["actor_id"] == "first"
    assert session(client, identity)["self_participation_id"] == before["self_participation_id"]
    with pytest.raises(NotFoundError):
        app.game_observations.observe("community", "first", identity)
    history = app.game_observations.events(
        "community", "first", identity, participation["participation_id"]
    )
    assert old_ids <= {event.event_id for event in history.items}
    app.character_state.set_availability("community", "first", "available", expected_version=1)
    rejoined, _ = invite(client, identity)
    new_id = rejoined["game_receipt"]["result"]["participation"]["participation_id"]
    assert new_id != participation["participation_id"]
    assert client.post(f"/api/games/{identity}/leave", json=leave).json() == withdrawn
    assert (
        app.game_observations.observe(
            "community", "first", identity
        ).context.access.participation_id
        == new_id
    )
    assert not old_ids.intersection(
        event.event_id
        for event in app.game_observations.events("community", "first", identity, new_id).items
    )


def test_current_character_observation_has_actual_view_opportunity_and_sources(client):
    app = client.app.state.application
    created, _ = create(client)
    identity = created["game_id"]
    invite(client, identity)
    operation(client, identity, "start")
    action, _ = move(client, identity, "alice", 7, 7)
    before = session(client, identity)
    observation = app.game_observations.observe("community", "first", identity)
    assert observation.view.state.stones[0].x == 7
    assert observation.view.opportunities[0].seat_id == "white"
    assert len(observation.view.opportunities[0].legal_actions) == 224
    assert (
        observation.view.state_version
        == observation.observation.state_version
        == action["state_version_after"]
    )
    assert observation.observation.observer == ActorRef("character", "first")
    assert observation.observation.audience == (ActorRef("character", "first"),)
    body = json.loads(observation.observation.content)
    assert body["game_type"] == "gomoku"
    assert body["events"]["items"][-1]["event_id"] in action["event_ids"]
    assert observation.observation.occurred_at_utc == observation.context.game.updated_at_utc
    assert session(client, identity) == before
    with pytest.raises(NotFoundError):
        app.game_observations.observe("community", "second", identity)
    with pytest.raises(NotFoundError):
        app.game_observations.observe("missing", "first", identity)
    with pytest.raises(NotFoundError):
        app.game_observations.events(
            "community", "second", identity, observation.context.access.participation_id
        )
    with app.database.read() as connection:
        tasks_before = connection.execute("SELECT count(*) FROM conversation_tasks").fetchone()[0]
    app.intake.send(
        "community",
        created["conversation"]["conversation_id"],
        PlayerMessage(player_id="alice", client_message_id="game-message", text="轮到你了。"),
    )
    with app.database.read() as connection:
        assert (
            connection.execute("SELECT count(*) FROM conversation_tasks").fetchone()[0]
            == tasks_before
        )
        assert (
            connection.execute(
                "SELECT count(*) FROM input_batches WHERE conversation_id=?",
                (created["conversation"]["conversation_id"],),
            ).fetchone()[0]
            == 0
        )


def test_character_eligibility_rechecked_at_join_and_start_and_human_targets_rejected(client):
    app = client.app.state.application
    created, _ = create(client)
    identity = created["game_id"]
    body = {
        "player_id": "bob",
        "request_id": "unauthorized",
        "expected_state_version": 1,
        "seat_id": "white",
        "participant": {"kind": "character", "character_id": "first"},
    }
    assert client.post(f"/api/games/{identity}/participants", json=body).status_code == 403
    assert (
        client.get(
            f"/api/games/{identity}/participant-candidates", params={"player_id": "bob"}
        ).status_code
        == 403
    )
    body["player_id"] = "alice"
    body["participant"] = {"kind": "character", "character_id": "missing"}
    assert client.post(f"/api/games/{identity}/participants", json=body).status_code == 404
    body["participant"] = {"kind": "player", "player_id": "bob"}
    assert client.post(f"/api/games/{identity}/participants", json=body).status_code == 422
    app.character_state.set_availability("community", "first", "busy", expected_version=0)
    body["participant"] = {"kind": "character", "character_id": "first"}
    assert client.post(f"/api/games/{identity}/participants", json=body).status_code == 409
    assert (
        client.get(
            f"/api/games/{identity}/participant-candidates", params={"player_id": "alice"}
        ).json()["items"][0]["reason"]
        == "unavailable"
    )
    app.character_state.set_availability("community", "first", "available", expected_version=1)
    invite(client, identity)
    app.character_state.set_availability("community", "first", "offline", expected_version=2)
    assert not session(client, identity)["capabilities"]["can_start"]
    assert session(client, identity)["capabilities"]["start_blocked_reason"] == "unavailable"
    response = client.post(
        f"/api/games/{identity}/start",
        json={"player_id": "alice", "request_id": "start", "expected_state_version": 2},
    )
    assert response.status_code == 409
    assert session(client, identity)["game"]["status"] == "waiting"


def test_withdrawal_uses_actual_role_and_rolls_back_on_membership_failure(client):
    app = client.app.state.application
    created, _ = create(client)
    identity = created["game_id"]
    joined, _ = invite(client, identity)
    participation_id = joined["game_receipt"]["result"]["participation"]["participation_id"]
    with app.database.transaction() as connection:
        app.conversations.leave_in(
            connection,
            "community",
            created["conversation"]["conversation_id"],
            ActorRef("character", "first"),
        )
    body = {
        "player_id": "alice",
        "request_id": "withdraw",
        "expected_state_version": 2,
        "participation_id": participation_id,
    }
    assert client.post(f"/api/games/{identity}/leave", json=body).status_code == 404
    assert session(client, identity)["game"]["state_version"] == 2
    assert (
        client.get(
            f"/api/games/{identity}/operations/withdraw", params={"player_id": "alice"}
        ).status_code
        == 404
    )
    with app.database.transaction() as connection:
        app.conversations.join_in(
            connection,
            "community",
            created["conversation"]["conversation_id"],
            ActorRef("character", "first"),
        )
    assert client.post(f"/api/games/{identity}/leave", json=body).status_code == 200


def test_preparing_character_and_character_from_another_community_cannot_join(client):
    from support.authoring import confirm, create_draft

    draft, _ = create_draft(client, story="小时候住在河边，常和祖父一起下棋。")
    blueprint, _ = confirm(client, draft)
    response = client.post(
        "/api/communities/community/characters",
        json={
            "player_id": "alice",
            "blueprint_id": blueprint["blueprint_id"],
            "character_id": "preparing",
            "memory_mode": "full",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["memory_status"] == "preparing"
    app = client.app.state.application
    app.communities.create("另一社群", "UTC", community_id="other", player_id="alice")
    app.characters.create("other", "xiaojin", character_id="foreign", player_id="alice")
    created, _ = create(client)
    identity = created["game_id"]
    body = {
        "player_id": "alice",
        "request_id": "invite",
        "expected_state_version": 1,
        "seat_id": "white",
        "participant": {"kind": "character", "character_id": "preparing"},
    }
    response = client.post(f"/api/games/{identity}/participants", json=body)
    assert response.status_code == 409, response.text
    assert response.json()["error"]["code"] == "character_memory_not_ready"
    body["participant"]["character_id"] = "foreign"
    assert client.post(f"/api/games/{identity}/participants", json=body).status_code == 404
    assert session(client, identity)["game"]["state_version"] == 1


def test_restart_discovers_persisted_character_participation(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    with TestClient(create_app(settings)) as client:
        create_group(client, memory_mode="simple")
        created, _ = create(client)
        joined, _ = invite(client, created["game_id"])
        operation(client, created["game_id"], "start")
        expected = joined["game_receipt"]["result"]["participation"]["participation_id"]
    with TestClient(create_app(settings)) as client:
        service = client.app.state.application.game_observations
        assert service.participations("community", "first")[0].participation_id == expected
        assert (
            service.observe(
                "community", "first", created["game_id"]
            ).context.access.participation_id
            == expected
        )
