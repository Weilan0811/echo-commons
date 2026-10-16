import sqlite3

import pytest

from echo_games.public import (
    GameService,
    GomokuCreateGameCommand,
    JoinGameCommand,
    SeatAccess,
    StartGameCommand,
    default_registry,
)
from echo_games.schema import create_schema


@pytest.fixture
def system(tmp_path):
    connection = sqlite3.connect(tmp_path / "games.sqlite3", isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN IMMEDIATE")
    create_schema(connection)
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    try:
        yield GameService(default_registry()), connection
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def running(system):
    service, connection = system
    created = service.create_game(connection, "alice", GomokuCreateGameCommand(request_id="create"))
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
            seat_id=item.seat_id,
            participant_ref=item.participant_ref,
            participation_id=item.participation_id,
        )
        for item in (created.result.participation, joined.result.participation)
    )
    return service, connection, seats
