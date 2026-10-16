import sqlite3
from concurrent.futures import ThreadPoolExecutor

import pytest

from echo_games.public import (
    CancelGameCommand,
    GameError,
    GameListQuery,
    GameReadAccess,
    GameRegistry,
    GameService,
    GameStatus,
    GomokuCreateGameCommand,
    GomokuSubmitActionCommand,
    JoinGameCommand,
    LeaveGameCommand,
    PlaceStoneAction,
    ResignGameCommand,
    SeatAccess,
    StartGameCommand,
    default_registry,
)


def submit(service, connection, access, x, y, request_id):
    view = service.read_view(connection, access)
    command = GomokuSubmitActionCommand(
        request_id=request_id,
        opportunity_id=view.opportunities[0].opportunity_id,
        expected_state_version=view.state_version,
        action=PlaceStoneAction(x=x, y=y),
    )
    return command, service.submit_action(connection, access, command)


def assert_error(code, function, *args):
    with pytest.raises(GameError) as error:
        function(*args)
    assert error.value.code == code


def test_registry_exact_versions_and_real_directory(system):
    service, connection = system
    types = service.registry.list_game_types()
    assert [item.game_type for item in types] == ["gomoku"]
    assert types[0].rulesets[0].ruleset_id == "gomoku.freestyle"
    assert_error(
        "ruleset_unavailable",
        service.create_game,
        connection,
        "alice",
        GomokuCreateGameCommand(request_id="unknown", ruleset_version=2),
    )
    assert connection.execute("SELECT COUNT(*) FROM game_games").fetchone()[0] == 0


def test_create_join_retries_and_version_guards(system):
    service, connection = system
    command = GomokuCreateGameCommand(request_id="create")
    created = service.create_game(connection, "alice", command)
    assert created.state_version_after == 1
    assert service.create_game(connection, "alice", command) == created
    assert_error(
        "idempotency_conflict",
        service.create_game,
        connection,
        "alice",
        GomokuCreateGameCommand(request_id="create", initial_seat_id="white"),
    )
    assert_error(
        "game_not_ready",
        service.start_game,
        connection,
        "alice",
        StartGameCommand(game_id=created.game_id, request_id="start", expected_state_version=1),
    )
    join = JoinGameCommand(
        game_id=created.game_id,
        request_id="join",
        expected_state_version=1,
        participant_ref="bob",
        seat_id="white",
    )
    joined = service.join_game(connection, "bob", join)
    assert service.join_game(connection, "bob", join) == joined
    assert service.create_game(connection, "alice", command) == created
    assert service.read_operation(connection, "alice", created.game_id, "create") == created
    assert service.read_operation(connection, "bob", created.game_id, "create") is None
    assert_error(
        "state_version_conflict",
        service.start_game,
        connection,
        "alice",
        StartGameCommand(game_id=created.game_id, request_id="start", expected_state_version=1),
    )
    assert connection.execute("SELECT COUNT(*) FROM game_games").fetchone()[0] == 1


def test_participation_intervals_replay_and_audiences(system):
    service, connection = system
    created = service.create_game(connection, "alice", GomokuCreateGameCommand(request_id="create"))
    join = JoinGameCommand(
        game_id=created.game_id,
        request_id="join",
        expected_state_version=1,
        participant_ref="bob",
        seat_id="white",
    )
    joined = service.join_game(connection, "bob", join)
    old = joined.result.participation
    old_access = SeatAccess(
        game_id=created.game_id,
        seat_id="white",
        participant_ref="bob",
        participation_id=old.participation_id,
    )
    leave = LeaveGameCommand(
        game_id=created.game_id,
        request_id="leave",
        expected_state_version=2,
        participation_id=old.participation_id,
    )
    left = service.leave_game(connection, "bob", leave)
    replacement = service.join_game(
        connection,
        "carol",
        JoinGameCommand(
            game_id=created.game_id,
            request_id="join",
            expected_state_version=3,
            participant_ref="carol",
            seat_id="white",
        ),
    )
    new_access = SeatAccess(
        game_id=created.game_id,
        seat_id="white",
        participant_ref="carol",
        participation_id=replacement.result.participation.participation_id,
    )
    assert service.leave_game(connection, "bob", leave) == left
    assert service.join_game(connection, "bob", join) == joined
    summary = service.read_game(
        connection, GameReadAccess(game_id=created.game_id, requester_ref="carol")
    )
    assert summary.seats[1].occupant.participant_ref == "carol"
    assert "state" not in summary.model_dump()
    assert {event.type for event in service.read_events(connection, old_access).items} == {
        "participant_joined",
        "participant_left",
    }
    assert all(
        event.state_version == 4 for event in service.read_events(connection, new_access).items
    )
    assert service.read_receipt(connection, new_access, "old-action") is None
    assert_error("participation_not_found", service.read_view, connection, old_access)
    forged = old_access.model_copy(update={"participant_ref": "carol"})
    assert_error("participation_not_found", service.read_events, connection, forged)
    assert (
        service.find_participations(connection, ("bob",), (created.game_id,))[0].left_state_version
        == 3
    )


def test_seat_and_management_permissions(system):
    service, connection = system
    created = service.create_game(connection, "alice", GomokuCreateGameCommand(request_id="create"))
    for requester, participant, seat, code in (
        ("bob", "carol", "white", "operation_forbidden"),
        ("bob", "bob", "black", "seat_occupied"),
        ("alice", "alice", "white", "participant_already_seated"),
        ("bob", "bob", "blue", "invalid_seat"),
    ):
        assert_error(
            code,
            service.join_game,
            connection,
            requester,
            JoinGameCommand(
                game_id=created.game_id,
                request_id="rejected",
                expected_state_version=1,
                participant_ref=participant,
                seat_id=seat,
            ),
        )
    invited = service.join_game(
        connection,
        "alice",
        JoinGameCommand(
            game_id=created.game_id,
            request_id="invite",
            expected_state_version=1,
            participant_ref="character:mio",
            seat_id="white",
        ),
    )
    service.leave_game(
        connection,
        "alice",
        LeaveGameCommand(
            game_id=created.game_id,
            request_id="withdraw",
            expected_state_version=2,
            participation_id=invited.result.participation.participation_id,
        ),
    )
    creator_left = service.leave_game(
        connection,
        "alice",
        LeaveGameCommand(
            game_id=created.game_id,
            request_id="leave",
            expected_state_version=3,
            participation_id=created.result.participation.participation_id,
        ),
    )
    assert creator_left.status_after is GameStatus.CANCELLED


def test_action_receipt_is_stable_after_opportunity_and_state_change(running):
    service, connection, (black, white) = running
    decision = service.read_view(connection, black)
    frozen = service.read_decision_input(
        connection, black, decision.opportunities[0].opportunity_id
    )
    assert frozen.view.state_version == frozen.opportunity.expected_state_version == 3
    assert len(frozen.opportunity.legal_actions) == 225
    command, receipt = submit(service, connection, black, 7, 7, "move-1")
    assert receipt.state_version_after == 4
    assert service.submit_action(connection, black, command) == receipt
    assert service.read_receipt(connection, black, "move-1") == receipt
    assert service.read_receipt(connection, white, "move-1") is None
    assert_error(
        "idempotency_conflict",
        service.submit_action,
        connection,
        black,
        command.model_copy(update={"action": PlaceStoneAction(x=8, y=8)}),
    )
    assert_error(
        "opportunity_expired",
        service.read_decision_input,
        connection,
        black,
        command.opportunity_id,
    )
    assert len(service.list_open_opportunities(connection, (black, white))) == 1
    assert service.list_open_opportunities(connection, (black,)) == ()
    white_view = service.read_view(connection, white)
    invalid = GomokuSubmitActionCommand(
        request_id="bad",
        opportunity_id=white_view.opportunities[0].opportunity_id,
        expected_state_version=4,
        action=PlaceStoneAction(x=7, y=7),
    )
    assert_error("illegal_action", service.submit_action, connection, white, invalid)
    assert service.read_view(connection, white) == white_view
    assert service.read_receipt(connection, white, "bad") is None
    assert_error(
        "state_version_conflict",
        service.submit_action,
        connection,
        white,
        invalid.model_copy(update={"expected_state_version": 3}),
    )
    assert_error(
        "opportunity_expired",
        service.submit_action,
        connection,
        white,
        invalid.model_copy(update={"opportunity_id": command.opportunity_id}),
    )
    assert_error(
        "not_current_actor",
        service.submit_action,
        connection,
        black,
        invalid.model_copy(update={"request_id": "not-my-turn"}),
    )


def test_real_game_finishes_and_retains_original_receipts(running):
    service, connection, (black, white) = running
    original_command = original_receipt = None
    for index in range(5):
        command, receipt = submit(service, connection, black, index, 0, f"black-{index}")
        if index == 0:
            original_command, original_receipt = command, receipt
        if index < 4:
            submit(service, connection, white, index * 2, 14, f"white-{index}")
    view = service.read_view(connection, black)
    assert view.status is GameStatus.FINISHED
    assert view.state.result.winner_seat_id == "black"
    assert view.opportunities == ()
    assert service.submit_action(connection, black, original_command) == original_receipt
    events = service.read_events(connection, black).items
    assert events[-1].type == "game_finished"
    assert len([event for event in events if event.type == "stone_placed"]) == 9
    assert_error(
        "game_finished",
        service.submit_action,
        connection,
        white,
        GomokuSubmitActionCommand(
            request_id="late",
            opportunity_id=original_command.opportunity_id,
            expected_state_version=view.state_version,
            action=PlaceStoneAction(x=10, y=10),
        ),
    )


def test_restart_commit_and_rollback_are_caller_owned(running, tmp_path):
    service, connection, (black, white) = running
    filename = connection.execute("PRAGMA database_list").fetchone()[2]
    connection.commit()
    connection.execute("BEGIN IMMEDIATE")
    command, receipt = submit(service, connection, black, 7, 7, "rolled-back")
    connection.rollback()
    connection.execute("BEGIN")
    assert service.read_receipt(connection, black, command.request_id) is None
    assert service.read_view(connection, black).state.stones == ()
    assert connection.execute("SELECT COUNT(*) FROM game_action_receipts").fetchone()[0] == 0
    connection.rollback()
    connection.execute("BEGIN IMMEDIATE")
    _, receipt = submit(service, connection, black, 7, 7, "committed")
    connection.commit()
    with sqlite3.connect(filename, isolation_level=None) as restarted:
        restarted.execute("PRAGMA foreign_keys=ON")
        restarted.execute("BEGIN")
        new_service = GameService(default_registry())
        assert new_service.read_receipt(restarted, black, "committed") == receipt
        assert new_service.read_view(restarted, white).state.stones[0].x == 7
        assert new_service.read_view(restarted, white).opportunities
        assert restarted.execute("PRAGMA foreign_key_check").fetchall() == []
    with pytest.raises(RuntimeError, match="transaction"):
        service.create_game(
            connection, "alice", GomokuCreateGameCommand(request_id="no-transaction")
        )


def test_resignation_cancel_and_event_pagination(running):
    service, connection, (black, white) = running
    request = ResignGameCommand(
        game_id=black.game_id,
        request_id="resign",
        expected_state_version=3,
        participation_id=white.participation_id,
    )
    receipt = service.resign_game(connection, "bob", request)
    assert service.resign_game(connection, "bob", request) == receipt
    assert receipt.result.result.winner_seat_id == "black"
    assert service.read_view(connection, black).opportunities == ()
    assert_error(
        "game_finished",
        service.cancel_game,
        connection,
        "alice",
        CancelGameCommand(
            game_id=black.game_id,
            request_id="cancel",
            expected_state_version=4,
            reason="stop",
        ),
    )
    first = service.read_events(connection, black, limit=2)
    assert first.has_more
    second = service.read_events(connection, black, after_sequence=first.next_sequence, limit=200)
    assert not second.has_more
    assert len({e.event_id for e in (*first.items, *second.items)}) == 6
    old_events = service.read_events(connection, black, through_state_version=3)
    assert all(e.state_version <= 3 for e in old_events.items)
    assert_error(
        "idempotency_conflict",
        service.leave_game,
        connection,
        "bob",
        LeaveGameCommand(
            game_id=black.game_id,
            request_id="resign",
            expected_state_version=3,
            participation_id=white.participation_id,
        ),
    )


def test_cancel_replay_and_game_lists(system):
    service, connection = system
    created = service.create_game(connection, "alice", GomokuCreateGameCommand(request_id="create"))
    cancel = CancelGameCommand(
        game_id=created.game_id,
        request_id="cancel",
        expected_state_version=1,
        reason="changed plans",
    )
    receipt = service.cancel_game(connection, "alice", cancel)
    assert service.cancel_game(connection, "alice", cancel) == receipt
    assert service.list_games(connection, GameListQuery(game_ids=())).items == ()
    listed = service.list_games(
        connection, GameListQuery(game_ids=(created.game_id,), status="cancelled")
    )
    assert listed.items[0].cancel_reason == "changed plans"
    assert (
        service.list_games(
            connection, GameListQuery(game_ids=(created.game_id,), status="waiting")
        ).items
        == ()
    )
    unavailable = GameService(GameRegistry(()))
    assert_error(
        "ruleset_unavailable",
        unavailable.read_game,
        connection,
        GameReadAccess(game_id=created.game_id, requester_ref="alice"),
    )


def test_two_real_connections_cannot_join_the_same_seat(system):
    service, connection = system
    created = service.create_game(connection, "alice", GomokuCreateGameCommand(request_id="create"))
    path = connection.execute("PRAGMA database_list").fetchone()[2]
    connection.commit()

    def join(subject):
        contender = sqlite3.connect(path, isolation_level=None)
        try:
            contender.execute("PRAGMA foreign_keys=ON")
            contender.execute("BEGIN IMMEDIATE")
            try:
                service.join_game(
                    contender,
                    subject,
                    JoinGameCommand(
                        game_id=created.game_id,
                        request_id="join",
                        expected_state_version=1,
                        participant_ref=subject,
                        seat_id="white",
                    ),
                )
            except GameError as error:
                contender.rollback()
                return error.code
            contender.commit()
            return "joined"
        finally:
            contender.close()

    with ThreadPoolExecutor(max_workers=2) as executor:
        assert sorted(executor.map(join, ("bob", "carol"))) == ["joined", "state_version_conflict"]
    connection.execute("BEGIN")
    assert (
        connection.execute(
            "SELECT COUNT(*) FROM game_participations WHERE game_id=? AND seat_id='white'",
            (created.game_id,),
        ).fetchone()[0]
        == 1
    )
