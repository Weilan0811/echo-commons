import itertools
import random

import pytest
from pydantic import ValidationError

from echo_games.aeroplane import board
from echo_games.aeroplane.rules import AeroplaneRules
from echo_games.public import (
    AeroplaneConfig,
    AeroplaneCreateGameCommand,
    AeroplaneResult,
    AeroplaneState,
    DiceRolled,
    EndMoveAction,
    FlyShortcutAction,
    GameError,
    JumpFourAction,
    MoveEnded,
    MovePlaneAction,
    Plane,
    PlaneFlew,
    PlaneJumped,
    PlaneSentBack,
    PlaneTookOff,
    PlaneWalked,
    ReturnPenaltyAction,
    RollDiceAction,
    TakeOffAction,
)


def seed_for(*dice: int) -> int:
    # 找一个真实随机种子，使注入的随机源依次掷出指定点数；不伪造随机实现。
    for seed in itertools.count():
        source = random.Random(seed)
        if all(source.randint(1, 6) == value for value in dice):
            return seed
    raise AssertionError("unreachable")


def build(seat_order, on_board, **changes):
    """on_board 为 {席位: {棋子号: step}}；没有列出的棋子停在机场（step=None）。"""
    planes = tuple(
        Plane(seat_id=seat, plane_id=plane_id, step=on_board.get(seat, {}).get(plane_id))
        for seat in seat_order
        for plane_id in (1, 2, 3, 4)
    )
    return AeroplaneState(seat_order=seat_order, planes=planes, **changes)


def step_of(state, seat, plane_id):
    return next(
        plane.step
        for plane in state.planes
        if plane.seat_id == seat and plane.plane_id == plane_id
    )


def test_lineup_and_legal_actions_belong_to_the_current_seat():
    rules = AeroplaneRules(random.Random(0))
    state = rules.initialize(AeroplaneConfig(), ("red", "blue"))
    assert state.seat_order == ("red", "blue") and state.current_seat_id == "red"
    assert state.phase == "awaiting_roll" and state.dice is None
    assert len(state.planes) == 8 and all(plane.step is None for plane in state.planes)
    assert rules.observe(state, "red") == rules.observe(state, "blue") == state
    assert rules.phase(state) == "awaiting_roll" and rules.outcome(state) is None
    assert rules.legal_actions(state, "red") == (RollDiceAction(),)
    assert rules.legal_actions(state, "blue") == ()


def test_rotation_only_visits_seated_colours():
    rules = AeroplaneRules(random.Random(0))
    order = ("red", "blue", "green")
    for seat, following in (("red", "blue"), ("blue", "green"), ("green", "red")):
        state = build(order, {seat: {1: 1}}, current_seat_id=seat, phase="awaiting_action", dice=2)
        moved = rules.apply(state, seat, MovePlaneAction(plane_id=1)).state
        assert moved.current_seat_id == following and moved.phase == "awaiting_roll"


def test_roll_reads_the_injected_source_and_a_six_grants_another_roll():
    rules = AeroplaneRules(random.Random(seed_for(6, 3)))
    state = rules.initialize(AeroplaneConfig(), ("red", "yellow"))
    first = rules.apply(state, "red", RollDiceAction())
    assert first.result == DiceRolled(seat_id="red", dice=6)
    assert first.events == (DiceRolled(seat_id="red", dice=6),)
    rolled = first.state
    assert rolled.phase == "awaiting_action" and rolled.consecutive_sixes == 1
    assert rules.legal_actions(rolled, "red") == (
        TakeOffAction(plane_id=1),
        TakeOffAction(plane_id=2),
        TakeOffAction(plane_id=3),
        TakeOffAction(plane_id=4),
    )
    took = rules.apply(rolled, "red", TakeOffAction(plane_id=1))
    assert took.result == PlaneTookOff(seat_id="red", plane_id=1)
    assert step_of(took.state, "red", 1) == board.WAITING_STEP
    assert took.state.phase == "awaiting_roll" and took.state.current_seat_id == "red"
    assert took.state.consecutive_sixes == 1
    second = rules.apply(took.state, "red", RollDiceAction())
    assert second.result == DiceRolled(seat_id="red", dice=3)
    assert second.state.consecutive_sixes == 0
    advanced = rules.apply(second.state, "red", MovePlaneAction(plane_id=1)).state
    # 待飞位前进 3：-1 + 3 = 2
    assert step_of(advanced, "red", 1) == 2
    assert advanced.current_seat_id == "yellow" and advanced.phase == "awaiting_roll"


def test_take_off_waits_at_the_gate_and_landing_on_the_launch_cell_captures():
    rules = AeroplaneRules(random.Random(seed_for(1)))
    # 黄 step 39 的格号与红起飞处同为 0：(13 + 39) % 52 = 0
    state = build(
        ("red", "yellow"),
        {"yellow": {2: 39}},
        current_seat_id="red",
        phase="awaiting_action",
        dice=6,
    )
    took = rules.apply(state, "red", TakeOffAction(plane_id=1))
    assert took.result == PlaneTookOff(seat_id="red", plane_id=1)
    # 起飞只进入待飞位，跑道上的黄机不因此返回；六追加掷骰
    assert step_of(took.state, "red", 1) == board.WAITING_STEP
    assert step_of(took.state, "yellow", 2) == 39
    assert took.state.phase == "awaiting_roll" and took.state.current_seat_id == "red"
    landed = rules.apply(took.state, "red", RollDiceAction())
    assert landed.result == DiceRolled(seat_id="red", dice=1)
    moved = rules.apply(landed.state, "red", MovePlaneAction(plane_id=1))
    # 掷 1 恰好踏上起飞格并捕获该格上的黄机
    assert moved.result == PlaneWalked(
        seat_id="red", plane_id=1, from_step=board.WAITING_STEP, to_step=0
    )
    assert PlaneSentBack(seat_id="yellow", plane_id=2, reason="captured") in moved.events
    assert step_of(moved.state, "yellow", 2) is None
    # 起飞格与自家起飞格同色，连锁给出跳四格
    assert moved.state.phase == "awaiting_chain"
    assert rules.legal_actions(moved.state, "red") == (
        JumpFourAction(plane_id=1),
        EndMoveAction(),
    )


def test_waiting_planes_are_not_captured_on_the_ring():
    rules = AeroplaneRules(random.Random(0))
    # 红待飞位的虚拟格号是 51；黄 step 38 的格号同为 51：(13 + 38) % 52 = 51。
    # 待飞棋子不在跑道上，黄机踏上该格不捕获红机。
    state = build(
        ("red", "yellow"),
        {"red": {1: board.WAITING_STEP}, "yellow": {2: 34}},
        current_seat_id="yellow",
        phase="awaiting_action",
        dice=4,
    )
    moved = rules.apply(state, "yellow", MovePlaneAction(plane_id=2))
    assert moved.result == PlaneWalked(seat_id="yellow", plane_id=2, from_step=34, to_step=38)
    assert not any(isinstance(event, PlaneSentBack) for event in moved.events)
    assert step_of(moved.state, "red", 1) == board.WAITING_STEP
    assert moved.state.current_seat_id == "red" and moved.state.phase == "awaiting_roll"


def test_walking_captures_shared_cells_and_takeoff_colour_landing_offers_a_jump():
    rules = AeroplaneRules(random.Random(0))
    # 红步 16 走 4 到步 20（与自家起飞格同色）；蓝 step 46 的格号同为 20：(26 + 46) % 52 = 20
    state = build(
        ("red", "blue"), {"red": {1: 16}, "blue": {2: 46}}, current_seat_id="red",
        phase="awaiting_action", dice=4,
    )
    walked = rules.apply(state, "red", MovePlaneAction(plane_id=1))
    assert walked.result == PlaneWalked(seat_id="red", plane_id=1, from_step=16, to_step=20)
    assert PlaneSentBack(seat_id="blue", plane_id=2, reason="captured") in walked.events
    assert step_of(walked.state, "blue", 2) is None
    assert walked.state.phase == "awaiting_chain"
    assert rules.legal_actions(walked.state, "red") == (
        JumpFourAction(plane_id=1),
        EndMoveAction(),
    )
    jumped = rules.apply(walked.state, "red", JumpFourAction(plane_id=1))
    assert jumped.result == PlaneJumped(seat_id="red", plane_id=1, from_step=20, to_step=24)
    # 跳四格恰好落在自家虚线起点上，连锁转为飞越；飞越是「跳到」连锁不再延续，
    # 非六直接交接
    assert jumped.state.phase == "awaiting_chain"
    assert rules.legal_actions(jumped.state, "red") == (
        FlyShortcutAction(plane_id=1),
        EndMoveAction(),
    )
    flew = rules.apply(jumped.state, "red", FlyShortcutAction(plane_id=1))
    assert flew.result == PlaneFlew(
        seat_id="red",
        plane_id=1,
        from_step=board.SHORTCUT_STEP["red"],
        to_step=board.SHORTCUT_LANDING_STEP["red"],
    )
    assert flew.state.phase == "awaiting_roll" and flew.state.current_seat_id == "blue"


def test_walking_onto_the_shortcut_flies_without_capturing_the_home_lane():
    rules = AeroplaneRules(random.Random(0))
    # 蓝机停在自家归航道第 5 格；飞越只前进 12 格，不再吃掉归航道上的棋子。
    state = build(
        ("red", "blue"),
        {"red": {1: board.SHORTCUT_STEP["red"] - 4}, "blue": {3: board.HOMESTRETCH_FIRST_STEP + 4}},
        current_seat_id="red",
        phase="awaiting_action",
        dice=4,
    )
    walked = rules.apply(state, "red", MovePlaneAction(plane_id=1))
    assert walked.result == PlaneWalked(
        seat_id="red",
        plane_id=1,
        from_step=board.SHORTCUT_STEP["red"] - 4,
        to_step=board.SHORTCUT_STEP["red"],
    )
    assert walked.state.phase == "awaiting_chain"
    assert rules.legal_actions(walked.state, "red") == (
        FlyShortcutAction(plane_id=1),
        EndMoveAction(),
    )
    flew = rules.apply(walked.state, "red", FlyShortcutAction(plane_id=1))
    assert flew.result == PlaneFlew(
        seat_id="red",
        plane_id=1,
        from_step=board.SHORTCUT_STEP["red"],
        to_step=board.SHORTCUT_LANDING_STEP["red"],
    )
    assert not any(isinstance(event, PlaneSentBack) for event in flew.events)
    assert step_of(flew.state, "blue", 3) == board.HOMESTRETCH_FIRST_STEP + 4
    # 踏上虚线格飞越后的落点与自家起飞格同色，仍可再跳四格
    assert flew.state.phase == "awaiting_chain"
    assert rules.legal_actions(flew.state, "red") == (
        JumpFourAction(plane_id=1),
        EndMoveAction(),
    )
    ended = rules.apply(flew.state, "red", EndMoveAction())
    assert ended.result == MoveEnded(seat_id="red", plane_id=1)
    assert ended.state.current_seat_id == "blue" and ended.state.phase == "awaiting_roll"


def test_landing_on_the_shortcut_by_a_jump_can_still_fly():
    rules = AeroplaneRules(random.Random(0))
    state = build(
        ("red", "blue"),
        {"red": {1: board.SHORTCUT_STEP["red"]}},
        current_seat_id="red",
        phase="awaiting_chain",
        pending_plane_id=1,
        pending_arrival="jump",
    )
    # 跳到虚线格可以飞越，但飞越后不再跳格
    assert rules.legal_actions(state, "red") == (FlyShortcutAction(plane_id=1), EndMoveAction())


def test_home_stretch_bounce_uses_the_documented_formula():
    rules = AeroplaneRules(random.Random(0))
    state = build(
        ("red", "blue"), {"red": {1: 53}}, current_seat_id="red", phase="awaiting_action", dice=5
    )
    moved = rules.apply(state, "red", MovePlaneAction(plane_id=1))
    # 53 + 5 = 58 超过终点 56，反弹到 112 - 58 = 54
    assert moved.result == PlaneWalked(seat_id="red", plane_id=1, from_step=53, to_step=54)
    assert moved.state.phase == "awaiting_roll" and moved.state.result is None


def test_landing_exactly_on_home_completes_only_that_plane():
    rules = AeroplaneRules(random.Random(0))
    state = build(
        ("red", "blue"), {"red": {1: 53}}, current_seat_id="red", phase="awaiting_action", dice=3
    )
    moved = rules.apply(state, "red", MovePlaneAction(plane_id=1)).state
    assert step_of(moved, "red", 1) == 56
    assert moved.phase == "awaiting_roll" and moved.result is None


def test_first_seat_to_bring_all_four_planes_home_wins():
    rules = AeroplaneRules(random.Random(0))
    state = build(
        ("red", "blue"),
        {"red": {1: 53, 2: 56, 3: 56, 4: 56}},
        current_seat_id="red",
        phase="awaiting_action",
        dice=3,
    )
    moved = rules.apply(state, "red", MovePlaneAction(plane_id=1)).state
    assert moved.phase == "finished" and moved.current_seat_id is None
    assert moved.result == AeroplaneResult(winner_seat_id="red")
    assert rules.outcome(moved) == AeroplaneResult(winner_seat_id="red")
    assert rules.legal_actions(moved, "red") == ()
    with pytest.raises(GameError) as error:
        rules.apply(moved, "red", MovePlaneAction(plane_id=1))
    assert error.value.code == "game_finished"


def test_third_consecutive_six_returns_the_chosen_plane_and_ends_the_turn():
    rules = AeroplaneRules(random.Random(seed_for(6, 6, 6)))
    state = build(("red", "yellow"), {"red": {1: 5}}, current_seat_id="red")
    first = rules.apply(state, "red", RollDiceAction()).state
    assert first.consecutive_sixes == 1
    second = rules.apply(first, "red", MovePlaneAction(plane_id=1)).state
    assert step_of(second, "red", 1) == 11 and second.phase == "awaiting_roll"
    third = rules.apply(second, "red", RollDiceAction()).state
    assert third.consecutive_sixes == 2
    fourth = rules.apply(third, "red", MovePlaneAction(plane_id=1)).state
    assert step_of(fourth, "red", 1) == 17 and fourth.consecutive_sixes == 2
    fifth = rules.apply(fourth, "red", RollDiceAction())
    assert fifth.result == DiceRolled(seat_id="red", dice=6)
    assert fifth.state.phase == "awaiting_penalty" and fifth.state.consecutive_sixes == 3
    assert rules.legal_actions(fifth.state, "red") == (ReturnPenaltyAction(plane_id=1),)
    penalised = rules.apply(fifth.state, "red", ReturnPenaltyAction(plane_id=1))
    assert penalised.result == PlaneSentBack(seat_id="red", plane_id=1, reason="penalty")
    assert step_of(penalised.state, "red", 1) is None
    assert penalised.state.current_seat_id == "yellow" and penalised.state.phase == "awaiting_roll"


def test_third_six_without_board_planes_only_hands_over():
    rules = AeroplaneRules(random.Random(seed_for(6)))
    # 三枚已到终点、一枚在机场：连续第三次六时没有可返回的棋子，已到终点者不返回
    state = build(
        ("red", "yellow"),
        {"red": {1: 56, 2: 56, 3: 56}},
        current_seat_id="red",
        consecutive_sixes=2,
    )
    rolled = rules.apply(state, "red", RollDiceAction())
    assert rolled.result == DiceRolled(seat_id="red", dice=6)
    assert rolled.state.phase == "awaiting_roll" and rolled.state.current_seat_id == "yellow"
    assert step_of(rolled.state, "red", 1) == 56


def test_resign_is_not_supported_in_the_base_rules():
    rules = AeroplaneRules(random.Random(0))
    assert rules.supports_resign is False
    state = rules.initialize(AeroplaneConfig(), ("red", "yellow"))
    with pytest.raises(GameError) as error:
        rules.resign(state, "red")
    assert error.value.code == "operation_not_supported"


def test_illegal_actions_and_seat_ownership_are_rejected():
    rules = AeroplaneRules(random.Random(0))
    waiting = build(("red", "yellow"), {"red": {1: 5}}, current_seat_id="red")
    with pytest.raises(GameError) as error:
        rules.apply(waiting, "yellow", RollDiceAction())
    assert error.value.code == "not_current_actor"
    with pytest.raises(GameError) as error:
        rules.apply(waiting, "red", MovePlaneAction(plane_id=1))
    assert error.value.code == "illegal_action"
    acting = build(
        ("red", "yellow"), {"red": {1: 5}}, current_seat_id="red", phase="awaiting_action", dice=3
    )
    for action in (
        TakeOffAction(plane_id=4),
        MovePlaneAction(plane_id=4),
        JumpFourAction(plane_id=1),
        FlyShortcutAction(plane_id=1),
        ReturnPenaltyAction(plane_id=1),
        MovePlaneAction(plane_id=2),
    ):
        with pytest.raises(GameError) as error:
            rules.apply(acting, "red", action)
        assert error.value.code == "illegal_action"


def test_action_models_and_create_command_are_strict():
    for plane_id in (0, 5, True, "1", 1.5):
        with pytest.raises(ValidationError):
            MovePlaneAction(plane_id=plane_id)
    with pytest.raises(ValidationError):
        MovePlaneAction(plane_id=1, seat_id="red")
    with pytest.raises(ValidationError):
        RollDiceAction(plane_id=1)
    with pytest.raises(ValidationError):
        AeroplaneConfig(extra_field=1)
    command = AeroplaneCreateGameCommand(request_id="create")
    assert (command.game_type, command.ruleset_id, command.ruleset_version) == (
        "aeroplane",
        "aeroplane.traditional",
        1,
    )
    assert command.initial_seat_id == "red" and command.config == AeroplaneConfig()
    with pytest.raises(ValidationError):
        AeroplaneCreateGameCommand(request_id="create", initial_seat_id="purple")
    with pytest.raises(ValidationError):
        AeroplaneCreateGameCommand(request_id="create", game_type="gomoku")


def test_state_validator_enforces_lineup_and_phase_consistency():
    with pytest.raises(ValidationError):
        AeroplaneState(
            seat_order=("red",), planes=(Plane(seat_id="red", plane_id=1),), current_seat_id="red"
        )
    with pytest.raises(ValidationError):
        build(
            ("red", "yellow"),
            {},
            current_seat_id="red",
            result=AeroplaneResult(winner_seat_id="red"),
        )
    with pytest.raises(ValidationError):
        build(("red", "yellow"), {}, current_seat_id="red", phase="awaiting_chain")
    with pytest.raises(ValidationError):
        build(
            ("red", "yellow"), {}, current_seat_id="red", phase="awaiting_roll", pending_plane_id=1
        )
