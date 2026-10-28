import random
import sqlite3

import pytest

from echo_games.aeroplane.board import (
    HOME_STEP,
    LAST_RING_STEP,
    SEAT_ORDER,
    TAKEOFF_CELL,
    TRACK_LENGTH,
)
from echo_games.aeroplane.rules import AeroplaneRules
from echo_games.public import (
    AeroplaneCreateGameCommand,
    AeroplaneState,
    AeroplaneSubmitActionCommand,
    FlyShortcutAction,
    GameService,
    JoinGameCommand,
    JumpFourAction,
    MovePlaneAction,
    Plane,
    RollDiceAction,
    SeatAccess,
    StartGameCommand,
    default_registry,
)


def position(seat, step, *, dice=1, phase="awaiting_action", **fields):
    return AeroplaneState(
        seat_order=SEAT_ORDER,
        current_seat_id=seat,
        dice=dice,
        phase=phase,
        planes=tuple(
            Plane(
                seat_id=owner, plane_id=number, step=step if owner == seat and number == 1 else None
            )
            for owner in SEAT_ORDER
            for number in (1, 2, 3, 4)
        ),
        **fields,
    )


@pytest.mark.parametrize("seat", SEAT_ORDER)
def test_entry_has_own_colour_and_enters_home_without_an_extra_jump(seat):
    rules = AeroplaneRules(random.Random(0))
    assert (TAKEOFF_CELL[seat] + LAST_RING_STEP) % TRACK_LENGTH % 4 == SEAT_ORDER.index(seat)
    state = position(seat, 44, phase="awaiting_chain", pending_plane_id=1, pending_arrival="step")
    entered = rules.apply(state, seat, JumpFourAction(plane_id=1)).state
    assert next(p.step for p in entered.planes if p.seat_id == seat and p.plane_id == 1) == 48
    assert entered.phase == "awaiting_roll"
    moved = rules.apply(position(seat, 48), seat, MovePlaneAction(plane_id=1)).state
    assert next(p.step for p in moved.planes if p.seat_id == seat and p.plane_id == 1) == 49
    assert moved.phase == "awaiting_roll"


@pytest.mark.parametrize("seat", SEAT_ORDER)
def test_shortcut_runs_twelve_steps_between_own_colour_cells(seat):
    rules = AeroplaneRules(random.Random(0))
    state = position(seat, 16, phase="awaiting_chain", pending_plane_id=1, pending_arrival="step")
    assert FlyShortcutAction(plane_id=1) in rules.legal_actions(state, seat)
    moved = rules.apply(state, seat, FlyShortcutAction(plane_id=1))
    assert (moved.result.from_step, moved.result.to_step) == (16, 28)
    assert JumpFourAction(plane_id=1) in rules.legal_actions(moved.state, seat)


def test_finish_and_bounce_use_the_home_step():
    home, reflected = HOME_STEP, 52
    rules = AeroplaneRules(random.Random(0))
    moved = rules.apply(position("red", 53, dice=5), "red", MovePlaneAction(plane_id=1))
    assert moved.result.to_step == reflected
    state = position("red", home - 1)
    state = state.model_copy(
        update={
            "planes": tuple(
                p.model_copy(update={"step": home}) if p.seat_id == "red" and p.plane_id != 1 else p
                for p in state.planes
            )
        }
    )
    finished = rules.apply(state, "red", MovePlaneAction(plane_id=1)).state
    assert finished.phase == "finished" and finished.result.winner_seat_id == "red"


def test_restart_reads_state_and_dice_receipt(system):
    version = 1
    service, connection = system
    created = service.create_game(
        connection,
        "alice",
        AeroplaneCreateGameCommand(
            request_id=f"create-{version}",
            ruleset_version=version,
        ),
    )
    service.join_game(
        connection,
        "bob",
        JoinGameCommand(
            game_id=created.game_id,
            request_id="join",
            expected_state_version=1,
            participant_ref="bob",
            seat_id="yellow",
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
    participant = created.result.participation
    access = SeatAccess(
        game_id=created.game_id,
        seat_id="red",
        participant_ref="alice",
        participation_id=participant.participation_id,
    )
    view = service.read_view(connection, access)
    opportunity = view.opportunities[0]
    command = AeroplaneSubmitActionCommand(
        request_id="roll",
        action=RollDiceAction(),
        opportunity_id=opportunity.opportunity_id,
        expected_state_version=view.state_version,
    )
    receipt = service.submit_action(connection, access, command)
    before = service.read_view(connection, access)
    database_path = connection.execute("PRAGMA database_list").fetchone()[2]
    connection.commit()
    with sqlite3.connect(database_path) as reopened:
        reopened.execute("BEGIN")
        restored = GameService(default_registry())
        assert restored.read_view(reopened, access) == before
        assert before.ruleset_version == version
        assert restored.read_receipt(reopened, access, "roll") == receipt
