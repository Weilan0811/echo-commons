import asyncio
import json
import os
import signal
import sqlite3

import pytest
from echo_games.public import (
    GameService,
    GomokuCreateGameCommand,
    GomokuSubmitActionCommand,
    JoinGameCommand,
    PlaceStoneAction,
    SeatAccess,
    StartGameCommand,
    default_registry,
    preview_gomoku_actions,
    read_gomoku_tactics,
)
from echo_games.schema import create_schema
from support.application import settings_for

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.settings import load_settings
from echo_commons.infrastructure.game_analysis.rapfi.contracts import RapfiError
from echo_commons.infrastructure.game_analysis.rapfi.process import RapfiProcess
from echo_commons.modules.activities.gameplay.contracts import (
    AnalysisRequest,
    GameplayAnalysis,
    GameplayAnalysisError,
)
from echo_commons.modules.activities.gameplay.gomoku import GomokuAnalyzer
from echo_commons.modules.activities.gameplay.registry import GameplayRegistry


@pytest.fixture
def position(tmp_path):
    connection = sqlite3.connect(tmp_path / "game.sqlite3", isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN")
    create_schema(connection)
    service = GameService(default_registry())
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
            seat_id=p.seat_id,
            participant_ref=p.participant_ref,
            participation_id=p.participation_id,
        )
        for p in (created.result.participation, joined.result.participation)
    )

    def play(points):
        for x, y in points:
            board = service.read_view(connection, seats[0])
            access = seats[0] if board.state.current_seat_id == "black" else seats[1]
            board = service.read_view(connection, access)
            service.submit_action(
                connection,
                access,
                GomokuSubmitActionCommand(
                    request_id=f"move-{len(board.state.stones)}",
                    opportunity_id=board.opportunities[0].opportunity_id,
                    expected_state_version=board.state_version,
                    action=PlaceStoneAction(x=x, y=y),
                ),
            )
        board = service.read_view(connection, seats[0])
        access = seats[0] if board.state.current_seat_id == "black" else seats[1]
        return service.read_view(connection, access)

    try:
        yield play
    finally:
        connection.rollback()
        connection.close()


@pytest.fixture
def rapfi_settings():
    settings = load_settings().game_analysis.rapfi
    if not settings.executable_path().exists():
        pytest.skip("Install the real engine with: uv run python tools/install_rapfi.py")
    return settings


def request(view, suggestions=()):
    return AnalysisRequest(
        view=view, opportunity=view.opportunities[0], suggested_actions=suggestions
    )


def test_public_preview_uses_real_rules_and_does_not_change_position(position):
    view = position([(0, 0), (0, 14), (1, 0), (2, 14), (2, 0), (4, 14), (3, 0), (6, 14)])
    original = view.model_dump_json()
    assert read_gomoku_tactics(view).winning_actions == (PlaceStoneAction(x=4, y=0),)
    preview = preview_gomoku_actions(view, (PlaceStoneAction(x=4, y=0),))[0]
    assert preview.result.winner_seat_id == "black"
    assert not preview.opponent_winning_actions
    assert view.model_dump_json() == original


@pytest.mark.parametrize(
    "points,target",
    [
        ([(0, 0), (0, 14), (1, 0), (2, 14), (2, 0), (4, 14), (3, 0), (6, 14)], (4, 0)),
        (
            [(0, 0), (0, 14), (1, 0), (2, 14), (2, 0), (4, 14), (4, 0), (6, 14), (5, 0), (8, 14)],
            (3, 0),
        ),
        ([(0, 14), (14, 0), (2, 14), (14, 1), (4, 14), (14, 2), (6, 14), (14, 3)], (14, 4)),
    ],
)
def test_real_engine_immediate_win_defence_boundary_and_overline(
    position, rapfi_settings, points, target
):
    view = position(points)

    async def run():
        engine = RapfiProcess(rapfi_settings)
        try:
            result = await GameplayRegistry((GomokuAnalyzer(engine),)).analyze(request(view))
            action = PlaceStoneAction(x=target[0], y=target[1])
            candidate = next(c for c in result.candidates if c.action == action)
            codes = {fact.code for fact in candidate.facts}
            assert "wins_now" in codes or "blocks_winning_point" in codes
            assert result.legal_action_count == 225 - len(points)
            assert result.choice_required
            assert all(c.action in view.opportunities[0].legal_actions for c in result.candidates)
            assert result.runs[0].resources["weight"] == "mix9svqfreestyle_bsmix.bin.lz4"
        finally:
            await engine.close()
        assert engine.pid is None

    asyncio.run(run())


def test_suggestion_outside_top_candidates_has_real_analysis_and_shared_serializable_result(
    position, rapfi_settings
):
    view = position([(7, 7)])
    suggested = PlaceStoneAction(x=0, y=0)

    async def run():
        engine = RapfiProcess(rapfi_settings)
        try:
            result = await GameplayRegistry((GomokuAnalyzer(engine),)).analyze(
                request(view, (suggested,))
            )
            candidate = next(c for c in result.candidates if c.action == suggested)
            assert "suggestion" in candidate.origins
            assert candidate.estimates
            assert candidate.estimates[0].scale == "rapfi.raw"
            assert candidate.estimates[0].continuation[0] == suggested
            assert len(result.candidates) <= rapfi_settings.candidates
            restored = GameplayAnalysis[PlaceStoneAction].model_validate_json(
                result.model_dump_json()
            )
            assert restored == result
            # 同一结果供两种模型路径使用，4.1 不增加模型专用的第二份候选依据。
            assert (
                json.loads(result.model_dump_json())["candidates"][0]["action"]["type"]
                == "place_stone"
            )
            first_pid = engine.pid
            again = await engine.analyze(((7, 7, 2),), candidates=2, time_ms=100)
            assert engine.pid == first_pid
            assert again.lines
        finally:
            await engine.close()

    asyncio.run(run())


def test_opening_recommendation_does_not_mean_only_one_legal_action(position, rapfi_settings):
    view = position([])

    async def run():
        engine = RapfiProcess(rapfi_settings)
        try:
            result = await GameplayRegistry((GomokuAnalyzer(engine),)).analyze(request(view))
            assert result.legal_action_count == 225
            assert result.choice_required
            assert 1 <= len(result.candidates) <= rapfi_settings.candidates
        finally:
            await engine.close()

    asyncio.run(run())


def test_invalid_suggestion_opportunity_and_unsupported_game_do_not_start_engine(
    position, rapfi_settings
):
    view = position([(7, 7)])

    async def run():
        engine = RapfiProcess(rapfi_settings)
        registry = GameplayRegistry((GomokuAnalyzer(engine),))
        try:
            with pytest.raises(GameplayAnalysisError, match="legal"):
                await registry.analyze(request(view, (PlaceStoneAction(x=7, y=7),)))
            wrong = request(view).model_copy(
                update={
                    "opportunity": view.opportunities[0].model_copy(
                        update={"expected_state_version": view.state_version - 1}
                    )
                }
            )
            with pytest.raises(GameplayAnalysisError, match="opportunity"):
                await registry.analyze(wrong)
            with pytest.raises(GameplayAnalysisError, match="No gameplay analysis"):
                registry.resolve("aeroplane", "aeroplane.traditional", 1)
            assert engine.pid is None
        finally:
            await engine.close()

    asyncio.run(run())


def test_real_timeout_cancellation_and_process_failure_recovery(rapfi_settings):
    async def run():
        timed = RapfiProcess(rapfi_settings.model_copy(update={"timeout_seconds": 0.000001}))
        try:
            with pytest.raises(RapfiError) as error:
                await timed.analyze(((7, 7, 2),), candidates=4, time_ms=500)
            assert error.value.code == "analysis_timeout"
            assert timed.pid is None
        finally:
            await timed.close()
        engine = RapfiProcess(rapfi_settings)
        try:
            await engine.analyze(((7, 7, 2),), candidates=2, time_ms=100)
            first = engine.pid
            os.kill(first, signal.SIGTERM)
            await engine._process.wait()
            await engine.analyze(((7, 7, 2),), candidates=2, time_ms=100)
            assert engine.pid != first
            pending = asyncio.create_task(engine.analyze(((7, 7, 2),), candidates=8, time_ms=3000))
            await asyncio.sleep(0.03)
            pending.cancel()
            with pytest.raises(asyncio.CancelledError):
                await pending
            assert engine.pid is None
        finally:
            await engine.close()
        with pytest.raises(RapfiError, match="closed"):
            await engine.analyze((), candidates=1, time_ms=100)

    asyncio.run(run())


def test_application_owns_lazy_process_and_closes_it(tmp_path, rapfi_settings):
    async def run():
        settings = settings_for(tmp_path, workers=False)
        async with application_lifecycle(settings) as app:
            assert app.rapfi.pid is None
            await app.rapfi.analyze(((7, 7, 2),), candidates=2, time_ms=100)
            assert app.rapfi.pid is not None
        assert app.rapfi.pid is None

    asyncio.run(run())


def test_analysis_retries_real_timeouts_with_a_limit(position, rapfi_settings):
    view = position([(7, 7)])

    async def run():
        engine = RapfiProcess(rapfi_settings.model_copy(update={"timeout_seconds": 0.000001}))
        registry = GameplayRegistry((GomokuAnalyzer(engine),), max_attempts=2)
        try:
            with pytest.raises(GameplayAnalysisError) as error:
                await registry.analyze(request(view))
            assert error.value.failures == ("analysis_timeout", "analysis_timeout")
            assert engine.pid is None
        finally:
            await engine.close()

    asyncio.run(run())


def test_shared_process_serializes_different_actual_observations(position, rapfi_settings):
    white = position([(7, 7)])
    black = position([(7, 6)])

    async def run():
        engine = RapfiProcess(rapfi_settings)
        registry = GameplayRegistry((GomokuAnalyzer(engine),))
        try:
            results = await asyncio.gather(
                registry.analyze(request(white)), registry.analyze(request(black))
            )
            for result, view in zip(results, (white, black), strict=True):
                assert result.state_version == view.state_version
                assert result.participation_id == view.viewer_participation_id
                assert all(
                    c.action in view.opportunities[0].legal_actions for c in result.candidates
                )
            assert engine.pid is not None
        finally:
            await engine.close()

    asyncio.run(run())
