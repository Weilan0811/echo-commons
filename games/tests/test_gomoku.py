import pytest
from pydantic import ValidationError

from echo_games.gomoku.rules import GomokuRules
from echo_games.public import GameError, GomokuConfig, GomokuState, PlaceStoneAction, Stone


@pytest.mark.parametrize(
    "points",
    [
        [(x, 0) for x in range(5)],
        [(14, y) for y in range(5)],
        [(10 + d, 10 + d) for d in range(5)],
        [(10 + d, 4 - d) for d in range(5)],
        [(x, 0) for x in (0, 1, 2, 4, 5, 3)],
    ],
)
@pytest.mark.parametrize("winner", ["black", "white"])
def test_real_rules_win_in_every_direction_and_allow_overline(points, winner):
    rules = GomokuRules()
    state = rules.initialize(GomokuConfig(), ("black", "white"))
    for index, (x, y) in enumerate(points):
        if winner == "white":
            state = rules.apply(state, "black", PlaceStoneAction(x=index * 2, y=14)).state
        transition = rules.apply(state, winner, PlaceStoneAction(x=x, y=y))
        state, result = transition.state, transition.result
        assert (result.x, result.y, result.seat_id) == (x, y, winner)
        if index < len(points) - 1:
            assert state.result is None
            if winner == "black":
                state = rules.apply(state, "white", PlaceStoneAction(x=index * 2, y=14)).state
    assert state.result.reason == "line"
    assert state.result.winner_seat_id == winner
    assert state.current_seat_id is None
    assert rules.legal_actions(state, "black") == ()
    with pytest.raises(GameError, match="finished"):
        rules.apply(state, "white", PlaceStoneAction(x=14, y=0))


def test_turns_occupied_points_and_strict_coordinates():
    rules = GomokuRules()
    state = rules.initialize(GomokuConfig(), ("black", "white"))
    assert len(rules.legal_actions(state, "black")) == 225
    assert rules.legal_actions(state, "white") == ()
    with pytest.raises(GameError) as error:
        rules.apply(state, "white", PlaceStoneAction(x=7, y=7))
    assert error.value.code == "not_current_actor"
    state = rules.apply(state, "black", PlaceStoneAction(x=7, y=7)).state
    with pytest.raises(GameError) as error:
        rules.apply(state, "white", PlaceStoneAction(x=7, y=7))
    assert error.value.code == "illegal_action"
    assert len(rules.legal_actions(state, "white")) == 224
    for x in (-1, 15, True, "7", 1.5):
        with pytest.raises(ValidationError):
            PlaceStoneAction(x=x, y=0)
    with pytest.raises(ValidationError):
        PlaceStoneAction(x=0, y=0, seat_id="white")
    with pytest.raises(ValidationError):
        GomokuConfig(board_size=19)


def draw_points():
    black, white = [], []
    for y in range(15):
        for x in range(15):
            (black if (x // 2 + y) % 2 == 0 else white).append((x, y))
    return black, white


def test_draw_plays_all_225_moves_with_real_rules():
    black, white = draw_points()
    assert (len(black), len(white)) == (113, 112)
    state, rules = GomokuState(), GomokuRules()
    for index in range(113):
        state = rules.apply(
            state, "black", PlaceStoneAction(x=black[index][0], y=black[index][1])
        ).state
        if index < 112:
            assert state.result is None
            state = rules.apply(
                state, "white", PlaceStoneAction(x=white[index][0], y=white[index][1])
            ).state
            assert state.result is None
    assert state.result.reason == "board_full"
    assert state.result.winner_seat_id is None


def test_final_intersection_checks_win_before_full_board():
    # 从无五连的满盘分布调整少量棋子，最后一子同时填满棋盘并形成五连。
    black, white = draw_points()
    for point in ((2, 0), (3, 0)):
        white.remove(point)
        black.append(point)
    for point in ((8, 0), (12, 0)):
        black.remove(point)
        white.append(point)
    black.remove((2, 0))
    stones = tuple(
        item
        for index in range(112)
        for item in (
            Stone(x=black[index][0], y=black[index][1], seat_id="black"),
            Stone(x=white[index][0], y=white[index][1], seat_id="white"),
        )
    )
    state = GomokuState(stones=stones)
    # 每一步都经过规则检查，确认这个次序在最后一子之前没有结束。
    rules, replay = GomokuRules(), GomokuState()
    for stone in state.stones:
        replay = rules.apply(replay, stone.seat_id, PlaceStoneAction(x=stone.x, y=stone.y)).state
        assert replay.result is None
    result = rules.apply(state, "black", PlaceStoneAction(x=2, y=0)).state
    assert len(result.stones) == 225
    assert result.result.reason == "line"


def test_resignation_preserves_board_and_winner():
    rules = GomokuRules()
    assert rules.supports_resign is True
    state = rules.apply(GomokuState(), "black", PlaceStoneAction(x=7, y=7)).state
    finished = rules.resign(state, "black")
    assert finished.stones == state.stones
    assert finished.result.reason == "resignation"
    assert finished.result.winner_seat_id == "white"
