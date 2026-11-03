import argparse
import asyncio
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
from echo_games.public import (
    GomokuCreateGameCommand,
    GomokuSubmitActionCommand,
    GomokuView,
    PlaceStoneAction,
    ResignGameCommand,
    StartGameCommand,
)
from httpx_sse import connect_sse

import echo_commons
from echo_commons.agents.harness.prompt import read_prompt_resource
from echo_commons.app.main import create_app
from echo_commons.app.settings import load_settings
from echo_commons.modules.activities.gameplay.contracts import AnalysisRequest
from echo_commons.modules.activities.tasks.prompt import activity_messages
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

        async def serve():
            app.state.verification_loop = asyncio.get_running_loop()
            await server.serve(sockets=[endpoint])

        thread = threading.Thread(target=lambda: asyncio.run(serve()))
        thread.start()
        try:
            deadline = time.monotonic() + 10
            while not server.started:
                assert thread.is_alive() and time.monotonic() < deadline
                time.sleep(0.02)
            with httpx.Client(
                base_url=f"http://127.0.0.1:{endpoint.getsockname()[1]}", timeout=5, trust_env=False
            ) as client:
                yield client, app.state.application, app.state.verification_loop
        finally:
            server.should_exit = True
            thread.join(10)
            assert not thread.is_alive()
    assert not app.state.application.realtime.broker.subscriptions


def verify_http_game(client, application, *, loop, analyze=False):
    analysis = None
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
        if analyze and index == 8:
            observed = GomokuView.model_validate(view.json())
            result = asyncio.run_coroutine_threadsafe(
                application.game_analysis.analyze(
                    AnalysisRequest(
                        view=observed,
                        opportunity=observed.opportunities[0],
                    )
                ),
                loop,
            ).result(timeout=30)
            assert any(
                c.action.x == 4
                and c.action.y == 0
                and any(fact.code == "wins_now" for fact in c.facts)
                for c in result.candidates
            )
            assert (
                client.get(f"/api/games/{game_id}/view", params={"player_id": player}).json()
                == view.json()
            )
            analysis = result.model_dump(mode="json")
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
    return analysis


def verify_activity_input(application, loop, *, analyze):
    application.communities.update("community", expected_version=0, status="active")
    application.characters.create(
        "community",
        "xiaojin",
        character_id="activity-character",
        player_id="alice",
        memory_mode="simple",
    )
    alice = ActorRef("player", "alice")
    created = application.game_participation.create_game(
        alice,
        CreateGameSessionCommand(
            community_id="community", game=GomokuCreateGameCommand(request_id="activity-create")
        ),
    )
    application.game_participation.join_game(
        alice,
        JoinGameSessionCommand(
            game_id=created.game_id,
            request_id="activity-invite",
            expected_state_version=1,
            seat_id="white",
            participant=ActorRef("character", "activity-character"),
        ),
    )
    application.game_participation.start_game(
        alice,
        StartGameCommand(
            game_id=created.game_id,
            request_id="activity-start",
            expected_state_version=2,
        ),
    )
    with application.database.read() as connection:
        access = application.game_participation.seat_access(connection, alice, created.game_id)
        view = application.games.read_view(connection, access)
    application.game_participation.submit_action(
        alice,
        created.game_id,
        GomokuSubmitActionCommand(
            request_id="activity-move",
            opportunity_id=view.opportunities[0].opportunity_id,
            expected_state_version=view.state_version,
            action=PlaceStoneAction(x=7, y=7),
        ),
    )
    sent = application.intake.send(
        "community",
        created.conversation.conversation_id,
        PlayerMessage("alice", "activity-chat", "边线也许挺有趣。"),
    )
    method = (
        application.activity_context.prepare_turn
        if analyze
        else application.activity_context.prepare_reply
    )
    frozen = asyncio.run_coroutine_threadsafe(
        method("community", "activity-character", created.game_id, input_id="installed-activity"),
        loop,
    ).result(timeout=30)
    assert frozen.material.conversation.perspective.trigger_message_ids == (sent.message_id,)
    assert sent.message_id in activity_messages(frozen)[0].content
    assert (
        application.activity_context.restore("community", "activity-character", frozen.snapshot_id)
        == frozen
    )
    assert frozen.schema_version == 1
    assert frozen.material.decision_persona.mode == "direct"
    application.game_participation.resign_game(
        alice,
        ResignGameCommand(
            game_id=created.game_id,
            request_id="activity-resign",
            expected_state_version=4,
            participation_id=access.participation_id,
        ),
    )
    application.activity_reactions.scan()
    with application.database.read() as connection:
        opportunity = connection.execute(
            "SELECT kind,status FROM activity_reaction_opportunities WHERE game_id=?",
            (created.game_id,),
        ).fetchone()
        assert opportunity["kind"] == "settlement" and opportunity["status"] == "pending"
    assert read_prompt_resource("activity/expression.md")
    return {
        "kind": frozen.kind,
        "frozen_input": "passed",
        "packaged_prompts": "passed",
        "original_recovery": "passed",
        "event_opportunity": "passed",
        "expression_resource": "passed",
    }


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--rapfi-directory", type=Path)
    arguments = parser.parse_args()
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
        if arguments.rapfi_directory:
            settings = settings.model_copy(
                update={
                    "game_analysis": settings.game_analysis.model_copy(
                        update={
                            "rapfi": settings.game_analysis.rapfi.model_copy(
                                update={"directory": str(arguments.rapfi_directory.resolve())}
                            )
                        }
                    )
                }
            )
        with running_application(settings) as (client, application, loop):
            assert client.get("/health/ready").status_code == 200
            database = application.database
            with database.read() as connection:
                assert (
                    connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                    == 33
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
            analysis = verify_http_game(
                client,
                application,
                loop=loop,
                analyze=arguments.rapfi_directory is not None,
            )
            activity = verify_activity_input(
                application, loop, analyze=arguments.rapfi_directory is not None
            )
        assert application.rapfi.pid is None
        print(
            json.dumps(
                {
                    "host_startup": "passed",
                    "migration": 33,
                    "game_sql_resources": "passed",
                    "game_participation_and_chat": "passed",
                    "http_game": "passed",
                    "real_sse": "passed",
                    "model_calls": 0,
                    "game_analysis": analysis,
                    "activity_context": activity,
                }
            )
        )


if __name__ == "__main__":
    main()
