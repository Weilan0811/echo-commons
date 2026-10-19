import json
import socket
import threading
import time
from contextlib import contextmanager
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import echo_games
import httpx
import uvicorn
from echo_games.public import GomokuCreateGameCommand, ResignGameCommand, StartGameCommand
from httpx_sse import connect_sse

import echo_commons
from echo_commons.app.main import create_app
from echo_commons.app.settings import load_settings
from echo_commons.modules.communities.contracts import (
    CreateGameSessionCommand,
    EndGameActivityCommand,
    JoinGameSessionCommand,
)
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.shared.actors import ActorRef


@contextmanager
def running_application(settings):
    app = create_app(settings)
    with socket.socket() as endpoint:
        endpoint.bind(("127.0.0.1", 0))
        endpoint.listen()
        server = uvicorn.Server(
            uvicorn.Config(app, log_level="warning", timeout_graceful_shutdown=3)
        )
        thread = threading.Thread(target=server.run, kwargs={"sockets": [endpoint]})
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(0.02)
            with httpx.Client(
                base_url=f"http://127.0.0.1:{endpoint.getsockname()[1]}", timeout=5, trust_env=False
            ) as client:
                yield client, app.state.application
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive()
    assert not app.state.application.realtime.broker.subscriptions


def verify_http_game(client):
    position = client.get(
        "/api/communities/community/events/cursor", params={"player_id": "bob"}
    ).json()["cursor"]
    with connect_sse(
        client,
        "GET",
        "/api/communities/community/events",
        params={
            "player_id": "bob",
            "cursor": position,
        },
    ) as source:
        created = client.post(
            "/api/games",
            json={
                "player_id": "alice",
                "community_id": "community",
                "request_id": "http-create",
                "game_type": "gomoku",
                "ruleset_id": "gomoku.freestyle",
                "ruleset_version": 1,
                "initial_seat_id": "black",
            },
        )
        assert created.status_code == 201, created.text
        game_id = created.json()["game_id"]
        for event in source.iter_sse():
            if event.event == "game.changed":
                assert event.json() == {
                    "community_id": "community",
                    "game_id": game_id,
                    "state_version": 1,
                }
                break
        else:
            raise AssertionError("Missing installed game notification")
    joined = client.post(
        f"/api/games/{game_id}/participants",
        json={
            "player_id": "bob",
            "request_id": "http-join",
            "expected_state_version": 1,
            "seat_id": "white",
            "participant": {"kind": "player"},
        },
    )
    assert joined.status_code == 200, joined.text
    started = client.post(
        f"/api/games/{game_id}/start",
        json={
            "player_id": "alice",
            "request_id": "http-start",
            "expected_state_version": 2,
        },
    )
    assert started.status_code == 200, started.text
    coordinates = [(x, y) for x in range(4) for y in (0, 1)] + [(4, 0)]
    for index, (x, y) in enumerate(coordinates):
        player = "alice" if index % 2 == 0 else "bob"
        view = client.get(f"/api/games/{game_id}/view", params={"player_id": player})
        assert view.status_code == 200, view.text
        opportunity = view.json()["opportunities"][0]
        body = {
            "player_id": player,
            "request_id": f"http-move-{index}",
            "opportunity_id": opportunity["opportunity_id"],
            "expected_state_version": opportunity["expected_state_version"],
            "action": {"type": "place_stone", "x": x, "y": y},
        }
        action = client.post(f"/api/games/{game_id}/actions", json=body)
        assert action.status_code == 200, action.text
    summary = client.get(f"/api/games/{game_id}", params={"player_id": "alice"}).json()
    assert summary["game"]["result"] == {"reason": "line", "winner_seat_id": "black"}
    assert summary["game"]["state_version"] == 12
    history = client.get(f"/api/games/{game_id}/events", params={"player_id": "alice"}).json()
    assert sum(item["type"] == "stone_placed" for item in history["items"]) == 9
    ended = client.post(
        f"/api/games/{game_id}/end",
        json={
            "player_id": "alice",
            "request_id": "http-end",
            "expected_state_version": 12,
            "expected_conversation_version": 1,
        },
    )
    assert ended.status_code == 200 and ended.json()["game_receipt"] is None
    assert client.post(f"/api/games/{game_id}/actions", json=body).json() == action.json()
    assert (
        client.get(
            f"/api/games/{game_id}/actions/http-move-8", params={"player_id": "alice"}
        ).json()
        == action.json()
    )


def main() -> None:
    for module in (echo_games, echo_commons):
        assert "site-packages" in Path(module.__file__).resolve().parts
    with TemporaryDirectory(prefix="echo-games-host-installed-") as temporary:
        directory = Path(temporary)
        config = files("echo_commons").joinpath("resources/config/settings.toml")
        settings = load_settings(str(config)).model_copy(
            update={
                "database_path": str(directory / "application.sqlite3"),
                "asset_directory": str(directory / "assets"),
                "log_path": str(directory / "application.log"),
                "model_secrets_path": str(directory / "missing-secrets.toml"),
                "debug_capture_enabled": False,
                "worker_enabled": False,
            }
        )
        with running_application(settings) as (client, application):
            assert client.get("/health/ready").status_code == 200
            database = application.database
            with database.read() as connection:
                assert (
                    connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                    == 23
                )
                assert connection.execute("SELECT COUNT(*) FROM game_games").fetchone()[0] == 0
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            alice, bob = ActorRef("player", "alice"), ActorRef("player", "bob")
            for actor in (alice, bob):
                application.communities.register_player(actor.actor_id, player_id=actor.actor_id)
            application.communities.create(
                "安装验证", "UTC", community_id="community", player_id="alice"
            )
            application.communities.join("community", bob)
            created = application.game_participation.create_game(
                alice,
                CreateGameSessionCommand(
                    community_id="community", game=GomokuCreateGameCommand(request_id="create")
                ),
            )
            joined = application.game_participation.join_game(
                bob,
                JoinGameSessionCommand(
                    game_id=created.game_id,
                    request_id="join",
                    expected_state_version=1,
                    seat_id="white",
                    participant=bob,
                ),
            )
            application.game_participation.start_game(
                alice,
                StartGameCommand(
                    game_id=created.game_id, request_id="start", expected_state_version=2
                ),
            )
            application.game_participation.resign_game(
                bob,
                ResignGameCommand(
                    game_id=created.game_id,
                    request_id="resign",
                    expected_state_version=3,
                    participation_id=joined.game_receipt.result.participation.participation_id,
                ),
            )
            application.intake.send(
                "community",
                created.conversation.conversation_id,
                PlayerMessage(player_id="alice", client_message_id="chat", text="赛后交流"),
            )
            ended = application.game_participation.end_activity(
                alice,
                EndGameActivityCommand(
                    game_id=created.game_id,
                    request_id="end",
                    expected_state_version=4,
                    expected_conversation_version=1,
                ),
            )
            assert ended.game_receipt is None and ended.conversation.status == "archived"
            assert application.planner.plan() == ()
            assert (
                application.game_participation.create_game(
                    alice,
                    CreateGameSessionCommand(
                        community_id="community", game=GomokuCreateGameCommand(request_id="create")
                    ),
                )
                == created
            )
            with database.read() as connection:
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
                assert (
                    connection.execute("SELECT COUNT(*) FROM game_session_operations").fetchone()[0]
                    == 5
                )
                assert (
                    connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 0
                )
            verify_http_game(client)
        print(
            json.dumps(
                {
                    "host_startup": "passed",
                    "migration": 23,
                    "game_sql_resources": "passed",
                    "game_participation_and_chat": "passed",
                    "http_game": "passed",
                    "real_sse": "passed",
                    "model_calls": 0,
                }
            )
        )


if __name__ == "__main__":
    main()
