import json
import sqlite3
from importlib.resources import files
from importlib.util import find_spec
from pathlib import Path
from tempfile import TemporaryDirectory

import echo_games
from echo_games.public import (
    GameService,
    GameStatus,
    GomokuCreateGameCommand,
    GomokuSubmitActionCommand,
    JoinGameCommand,
    PlaceStoneAction,
    SeatAccess,
    StartGameCommand,
    default_registry,
)
from echo_games.schema import create_schema


def main() -> None:
    package_path = Path(echo_games.__file__).resolve()
    assert "site-packages" in package_path.parts, package_path
    assert find_spec("echo_commons") is None
    assert files("echo_games.sql").joinpath("0001_games.sql").is_file()
    with TemporaryDirectory(prefix="echo-games-installed-") as temporary:
        path = Path(temporary) / "games.sqlite3"
        connection = sqlite3.connect(path, isolation_level=None)
        connection.execute("PRAGMA foreign_keys=ON")
        connection.execute("BEGIN IMMEDIATE")
        create_schema(connection)
        service = GameService(default_registry())
        created = service.create_game(
            connection, "alice", GomokuCreateGameCommand(request_id="create")
        )
        joined = service.join_game(
            connection,
            "bob",
            JoinGameCommand(
                game_id=created.game_id,
                request_id="join",
                expected_state_version=1,
                participant_ref="bob",
                seat_id="white",
            ),
        )
        service.start_game(
            connection,
            "alice",
            StartGameCommand(
                game_id=created.game_id,
                request_id="start",
                expected_state_version=2,
            ),
        )
        seats = tuple(
            SeatAccess(
                game_id=created.game_id,
                seat_id=p.seat_id,
                participant_ref=p.participant_ref,
                participation_id=p.participation_id,
            )
            for p in (created.result.participation, joined.result.participation)
        )
        first_command = first_receipt = None
        for turn in range(9):
            access = seats[turn % 2]
            view = service.read_view(connection, access)
            command = GomokuSubmitActionCommand(
                request_id=f"move-{turn}",
                opportunity_id=view.opportunities[0].opportunity_id,
                expected_state_version=view.state_version,
                action=PlaceStoneAction(
                    x=turn // 2 if turn % 2 == 0 else turn - 1, y=0 if turn % 2 == 0 else 14
                ),
            )
            receipt = service.submit_action(connection, access, command)
            if turn == 0:
                first_command, first_receipt = command, receipt
        connection.commit()
        connection.close()
        restarted = sqlite3.connect(path, isolation_level=None)
        try:
            restarted.execute("PRAGMA foreign_keys=ON")
            restarted.execute("BEGIN IMMEDIATE")
            service = GameService(default_registry())
            view = service.read_view(restarted, seats[0])
            assert view.status is GameStatus.FINISHED
            assert view.state.result.winner_seat_id == "black"
            assert len(view.state.stones) == 9
            assert service.submit_action(restarted, seats[0], first_command) == first_receipt
            assert len(service.read_events(restarted, seats[0]).items) == 14
            assert restarted.execute("PRAGMA foreign_key_check").fetchall() == []
            print(
                json.dumps(
                    {
                        "package_path": str(package_path),
                        "host_installed": False,
                        "moves": 9,
                        "winner": "black",
                        "restart_and_retry": "passed",
                        "sql_resources": "passed",
                    },
                    ensure_ascii=False,
                )
            )
        finally:
            restarted.close()


if __name__ == "__main__":
    main()
