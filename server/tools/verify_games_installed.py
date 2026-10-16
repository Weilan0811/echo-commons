import json
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import echo_games
from echo_games.public import GomokuCreateGameCommand, ResignGameCommand, StartGameCommand
from fastapi.testclient import TestClient

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
        with TestClient(create_app(settings)) as client:
            assert client.get("/health/ready").status_code == 200
            database = client.app.state.application.database
            with database.read() as connection:
                assert (
                    connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                    == 22
                )
                assert connection.execute("SELECT COUNT(*) FROM game_games").fetchone()[0] == 0
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            application = client.app.state.application
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
        print(
            json.dumps(
                {
                    "host_startup": "passed",
                    "migration": 22,
                    "game_sql_resources": "passed",
                    "game_participation_and_chat": "passed",
                    "model_calls": 0,
                }
            )
        )


if __name__ == "__main__":
    main()
