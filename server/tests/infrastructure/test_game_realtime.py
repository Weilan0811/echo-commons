import json
from datetime import UTC, datetime, timedelta

import pytest
from echo_games.public import LeaveGameCommand
from httpx_sse import connect_sse
from support.application import settings_for
from support.games import create, move, operation, prepare_players, running_game, session
from support.realtime import cursor, next_event, running_server

from echo_commons.infrastructure.realtime.stream import EventCursor
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


@pytest.fixture
def live_game(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"model_secrets_path": str(tmp_path / "absent-credentials.toml")}
    )
    with running_server(settings) as (client, application):
        prepare_players(client)
        yield client, application


def stream(client, position, player="alice", headers=None):
    return connect_sse(
        client,
        "GET",
        "/api/communities/community/events",
        params={"player_id": player, "cursor": position},
        headers=headers or {},
    )


def test_real_sse_announces_created_game_and_actions_without_private_data(live_game):
    client, application = live_game
    alice, cara = cursor(client), cursor(client, "cara")
    with stream(client, alice) as first, stream(client, cara, "cara") as lobby:
        created, body = create(client)
        one = next_event(first.iter_sse(), "game.changed")
        other = next_event(lobby.iter_sse(), "game.changed")
        expected = {"community_id": "community", "game_id": created["game_id"], "state_version": 1}
        assert one.json() == other.json() == expected
    assert client.post("/api/games", json=body).json() == created
    after_create = application.realtime.validate("community", "alice", one.id)
    outgoing, _, _, _ = application.realtime.scan(after_create)
    assert all(item["event"] != "game.changed" for item in outgoing)
    operation(client, created["game_id"], "participants", player="bob", seat_id="white")
    operation(client, created["game_id"], "start")
    position = cursor(client)
    receipt, body = move(client, created["game_id"], "alice", 7, 7)
    # 初次读取之后才订阅，仍能补充在这个间隔内提交的变化。
    with stream(client, position) as source:
        changed = next_event(source.iter_sse(), "game.changed")
        assert changed.json() == {**expected, "state_version": receipt["state_version_after"]}
        assert set(changed.json()) == {"community_id", "game_id", "state_version"}
    assert client.post(f"/api/games/{created['game_id']}/actions", json=body).json() == receipt
    assert (
        client.get(
            f"/api/games/{created['game_id']}/view", params={"player_id": "cara"}
        ).status_code
        == 404
    )


def test_reconnect_uses_sse_position_and_formal_history_keeps_its_own_cursor(live_game):
    client, application = live_game
    created, _, _ = running_game(client)
    identity = created["game_id"]
    history = client.get(f"/api/games/{identity}/events", params={"player_id": "alice"}).json()
    before = cursor(client)
    first, _ = move(client, identity, "alice", 0, 0)
    with stream(client, before) as source:
        accepted = next_event(source.iter_sse(), "game.changed")
    second, _ = move(client, identity, "bob", 0, 1)
    with stream(client, before, headers={"Last-Event-ID": accepted.id}) as source:
        replay = next_event(source.iter_sse(), "game.changed")
        assert replay.json()["state_version"] == second["state_version_after"]
    events = client.get(
        f"/api/games/{identity}/events",
        params={
            "player_id": "alice",
            "cursor": history["cursor"],
        },
    ).json()
    assert [item["type"] for item in events["items"]] == ["stone_placed", "stone_placed"]
    assert [item["state_version"] for item in events["items"]] == [
        first["state_version_after"],
        second["state_version_after"],
    ]
    assert (
        client.get(
            f"/api/games/{identity}/events", params={"player_id": "bob", "cursor": events["cursor"]}
        ).status_code
        == 400
    )
    with application.database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM realtime_events WHERE kind='game.changed'"
            ).fetchone()[0]
            == 5
        )


def test_expired_sse_position_requires_resync_while_formal_game_events_remain(live_game):
    client, application = live_game
    created, _, _ = running_game(client)
    identity = created["game_id"]
    position = cursor(client)
    move(client, identity, "alice", 7, 7)
    with application.database.transaction() as connection:
        connection.execute(
            "UPDATE realtime_events SET created_at_utc=?",
            ((datetime.now(UTC) - timedelta(days=2)).isoformat(),),
        )
        assert application.database.events.clean(connection, datetime.now(UTC)) > 0
    with stream(client, position) as source:
        assert next_event(source.iter_sse(), "resync_required").json() == {
            "reason": "cursor_expired"
        }
    assert session(client, identity)["game"]["state_version"] == 4
    history = client.get(f"/api/games/{identity}/events", params={"player_id": "alice"}).json()
    assert history["items"][-1]["type"] == "stone_placed"
    assert history["cursor"]


def test_real_conversation_failure_rolls_back_game_notifications(live_game):
    client, application = live_game
    created, _ = create(client)
    joined, _ = operation(client, created["game_id"], "participants", player="bob", seat_id="white")
    with application.database.transaction() as connection:
        application.conversations.leave_in(
            connection,
            "community",
            created["conversation"]["conversation_id"],
            ActorRef("player", "bob"),
        )
    before = application.realtime.current("community", "alice")
    with pytest.raises(NotFoundError):
        application.game_participation.leave_game(
            ActorRef("player", "bob"),
            LeaveGameCommand(
                game_id=created["game_id"],
                request_id="failed-leave",
                expected_state_version=2,
                participation_id=joined["game_receipt"]["result"]["participation"][
                    "participation_id"
                ],
            ),
        )
    outgoing, after, _, _ = application.realtime.scan(before)
    assert outgoing == [] and after == before
    assert session(client, created["game_id"])["game"]["state_version"] == 2


def test_notifications_do_not_cross_community_or_player_cursor_scope(live_game):
    client, application = live_game
    assert (
        client.post(
            "/api/communities",
            json={"player_id": "outside", "community_id": "other", "name": "另一社群"},
        ).status_code
        == 201
    )
    before = cursor(client)
    other, _ = create(client, community_id="other", player="outside")
    outgoing, _, _, _ = application.realtime.scan(EventCursor.decode(before, "alice", "community"))
    assert all(item["event"] == "checkpoint" for item in outgoing)
    assert all(other["game_id"] not in item["data"] for item in outgoing)
    assert (
        client.get(
            "/api/communities/community/events/cursor", params={"player_id": "outside"}
        ).status_code
        == 404
    )
    assert (
        client.get(
            "/api/communities/community/events", params={"player_id": "bob", "cursor": before}
        ).status_code
        == 400
    )


def test_restart_keeps_game_receipts_and_replays_durable_game_notifications(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"model_secrets_path": str(tmp_path / "absent-credentials.toml")}
    )
    with running_server(settings) as (client, _):
        prepare_players(client)
        created, _, _ = running_game(client)
        identity = created["game_id"]
        before = cursor(client)
        receipt, body = move(client, identity, "alice", 3, 3, request_id="restart-move")
    with running_server(settings) as (client, _), stream(client, before) as source:
        event = next_event(source.iter_sse(), "game.changed")
        assert event.json()["game_id"] == identity
        assert event.json()["state_version"] == receipt["state_version_after"]
        assert (
            client.get(
                f"/api/games/{identity}/actions/restart-move", params={"player_id": "alice"}
            ).json()
            == receipt
        )
        assert client.post(f"/api/games/{identity}/actions", json=body).json() == receipt
        assert (
            json.loads(event.data)["state_version"]
            == session(client, identity)["game"]["state_version"]
        )
