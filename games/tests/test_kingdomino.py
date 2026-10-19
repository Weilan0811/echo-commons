import random

import pytest

from echo_games.kingdomino.models import (
    Cell,
    ChooseDominoAction,
    DiscardDominoAction,
    DominoChosen,
    DominoPlaced,
    Kingdom,
    KingdominoConfig,
    KingdominoState,
    LineSlot,
    PlaceDominoAction,
    PlaceInitialKingAction,
    SeatId,
)
from echo_games.kingdomino.rules import KingdominoRules
from echo_games.kingdomino.scoring import score_kingdoms
from echo_games.kingdomino.tiles import Terrain
from echo_games.public import GameError


def engine(seed: int = 0) -> KingdominoRules:
    return KingdominoRules(random.Random(seed))


def cell(x: int, y: int, terrain: Terrain, crowns: int = 0) -> Cell:
    return Cell(x=x, y=y, terrain=terrain, crowns=crowns)


def kingdom(seat: SeatId, *extra: Cell) -> Kingdom:
    start = Cell(x=0, y=0, terrain="field", start=True)
    return Kingdom(seat_id=seat, cells=(start, *extra))


def placing(
    *,
    line: tuple[LineSlot, ...],
    next_line: tuple[LineSlot, ...],
    kingdoms: tuple[Kingdom, ...],
    active_index: int = 0,
    deck: tuple[int, ...] = (),
    discarded: tuple[int, ...] = (),
) -> KingdominoState:
    return KingdominoState(
        seat_order=("pink", "yellow"),
        kings_per_seat=1,
        deck=deck,
        line=line,
        next_line=next_line,
        kingdoms=kingdoms,
        discarded=discarded,
        seeding_queue=(),
        active_index=active_index,
        phase="placing",
    )


def actor(rules: KingdominoRules, state: KingdominoState) -> str:
    return next(seat for seat in state.seat_order if rules.legal_actions(state, seat))


def take(rules: KingdominoRules, state: KingdominoState) -> KingdominoState:
    seat = actor(rules, state)
    actions = rules.legal_actions(state, seat)
    assert actions
    return rules.apply(state, seat, actions[0]).state


def assert_error(code: str, function, *args):
    with pytest.raises(GameError) as error:
        function(*args)
    assert error.value.code == code


def test_setup_matches_player_count():
    for seats, kings, deck_size in (
        (("pink", "yellow"), 2, 24),
        (("pink", "yellow", "green"), 1, 36),
        (("pink", "yellow", "green", "blue"), 1, 48),
    ):
        state = engine().initialize(KingdominoConfig(), seats)
        line = len(seats) * kings
        assert state.kings_per_seat == kings
        assert len(state.line) == line and len(state.next_line) == line
        assert len(state.deck) == deck_size - line * 2
        assert state.phase == "seeding" and state.result is None
        assert [slot.king_seat_id for slot in state.line] == [None] * line
        ids = [slot.domino_id for slot in state.line]
        assert ids == sorted(ids)
        for item in state.kingdoms:
            assert len(item.cells) == 1 and item.cells[0].start


def test_seeding_seats_every_king_in_draw_order():
    rules = engine(3)
    state = rules.initialize(KingdominoConfig(), ("pink", "yellow"))
    assert len(state.seeding_queue) == 4
    assert sorted(state.seeding_queue) == ["pink", "pink", "yellow", "yellow"]
    for _ in range(4):
        seat = actor(rules, state)
        assert seat == state.seeding_queue[state.seeds_drawn]
        assert rules.observe(state, seat).seeding_remaining == 4 - state.seeds_drawn
        actions = rules.legal_actions(state, seat)
        assert all(isinstance(item, PlaceInitialKingAction) for item in actions)
        assert len(actions) == len(state.line) - state.seeds_drawn
        state = rules.apply(state, seat, actions[0]).state
    assert state.phase == "placing" and state.seeding_queue == ()
    assert all(slot.king_seat_id is not None for slot in state.line)


def test_placement_must_connect_to_the_kingdom():
    rules = engine()
    kingdoms = (
        kingdom("pink", cell(1, 0, "lake"), cell(2, 0, "lake")),
        kingdom("yellow"),
    )
    state = placing(
        line=(
            LineSlot(domino_id=9, king_seat_id="pink"),
            LineSlot(domino_id=12, king_seat_id="yellow"),
        ),
        next_line=(LineSlot(domino_id=16), LineSlot(domino_id=19)),
        kingdoms=kingdoms,
    )
    actions = rules.legal_actions(state, "pink")
    # 第 9 张为麦田/森林：只贴到湖泊，既无相同地形也未触到起始地块。
    assert PlaceDominoAction(cell_x=3, cell_y=0, direction="right") not in actions
    # 触到起始地块视为万能相连。
    assert PlaceDominoAction(cell_x=0, cell_y=1, direction="right") in actions
    assert PlaceDominoAction(cell_x=0, cell_y=-1, direction="right") in actions


def test_placement_cannot_exceed_five_by_five():
    rules = engine()
    kingdoms = (
        kingdom(
            "pink",
            cell(1, 0, "field"),
            cell(2, 0, "field"),
            cell(3, 0, "field"),
            cell(4, 0, "field"),
        ),
        kingdom("yellow"),
    )
    state = placing(
        line=(
            LineSlot(domino_id=1, king_seat_id="pink"),
            LineSlot(domino_id=5, king_seat_id="yellow"),
        ),
        next_line=(LineSlot(domino_id=3), LineSlot(domino_id=4)),
        kingdoms=kingdoms,
    )
    actions = rules.legal_actions(state, "pink")
    # 向右会把宽度推到 6 格，超出 5×5；向上仍在外接矩形内且与麦田相接。
    assert PlaceDominoAction(cell_x=4, cell_y=1, direction="right") not in actions
    assert PlaceDominoAction(cell_x=4, cell_y=1, direction="up") in actions


def test_unplaceable_domino_is_discarded():
    rules = engine()
    kingdoms = (
        kingdom(
            "pink",
            cell(1, 0, "lake"),
            cell(-1, 0, "lake"),
            cell(0, 1, "lake"),
            cell(0, -1, "lake"),
        ),
        kingdom("yellow"),
    )
    state = placing(
        line=(
            LineSlot(domino_id=1, king_seat_id="pink"),
            LineSlot(domino_id=5, king_seat_id="yellow"),
        ),
        next_line=(LineSlot(domino_id=3), LineSlot(domino_id=4)),
        kingdoms=kingdoms,
    )
    # 起始地块四周已被湖泊占满，麦田/麦田无法以任何地形相接。
    assert rules.legal_actions(state, "pink") == (DiscardDominoAction(),)
    discarded = rules.apply(state, "pink", DiscardDominoAction()).state
    assert discarded.discarded == (1,)
    assert discarded.phase == "choosing"


def test_a_placement_must_be_used_while_one_exists():
    rules = engine()
    state = placing(
        line=(
            LineSlot(domino_id=1, king_seat_id="pink"),
            LineSlot(domino_id=5, king_seat_id="yellow"),
        ),
        next_line=(LineSlot(domino_id=3), LineSlot(domino_id=4)),
        kingdoms=(kingdom("pink"), kingdom("yellow")),
    )
    assert DiscardDominoAction() not in rules.legal_actions(state, "pink")
    assert_error("illegal_action", rules.apply, state, "pink", DiscardDominoAction())


def test_placing_then_choosing_advances_to_the_next_king():
    rules = engine()
    state = placing(
        line=(
            LineSlot(domino_id=1, king_seat_id="pink"),
            LineSlot(domino_id=5, king_seat_id="yellow"),
        ),
        next_line=(LineSlot(domino_id=3), LineSlot(domino_id=4)),
        kingdoms=(kingdom("pink"), kingdom("yellow")),
    )
    placement = rules.apply(state, "pink", PlaceDominoAction(cell_x=0, cell_y=1, direction="right"))
    assert isinstance(placement.result, DominoPlaced)
    assert placement.state.phase == "choosing"
    assert rules.legal_actions(placement.state, "yellow") == ()
    assert rules.legal_actions(placement.state, "pink") == (
        ChooseDominoAction(domino_id=3),
        ChooseDominoAction(domino_id=4),
    )
    choice = rules.apply(placement.state, "pink", ChooseDominoAction(domino_id=3))
    assert isinstance(choice.result, DominoChosen)
    assert choice.state.phase == "placing" and choice.state.active_index == 1
    assert choice.state.next_line[0].king_seat_id == "pink"
    assert actor(rules, choice.state) == "yellow"


def test_illegal_actions_are_rejected():
    rules = engine()
    state = placing(
        line=(
            LineSlot(domino_id=1, king_seat_id="pink"),
            LineSlot(domino_id=5, king_seat_id="yellow"),
        ),
        next_line=(LineSlot(domino_id=3), LineSlot(domino_id=4)),
        kingdoms=(kingdom("pink"), kingdom("yellow")),
    )
    assert_error(
        "not_current_actor",
        rules.apply,
        state,
        "yellow",
        PlaceDominoAction(cell_x=0, cell_y=1, direction="right"),
    )
    assert_error("illegal_action", rules.apply, state, "pink", ChooseDominoAction(domino_id=3))
    assert_error(
        "illegal_action",
        rules.apply,
        state,
        "pink",
        PlaceDominoAction(cell_x=0, cell_y=0, direction="right"),
    )
    seeding = rules.initialize(KingdominoConfig(), ("pink", "yellow"))
    seat = actor(rules, seeding)
    taken = rules.legal_actions(seeding, seat)[0]
    seeded = rules.apply(seeding, seat, taken).state
    assert_error("illegal_action", rules.apply, seeded, actor(rules, seeded), taken)


def test_scoring_sums_domains_and_breaks_ties():
    pink = kingdom("pink", cell(1, 0, "field", 1))
    other = kingdom("yellow", cell(1, 0, "lake"), cell(2, 0, "lake"))
    result = score_kingdoms((pink, other))
    assert result.winner_seat_ids == ("pink",)
    assert (result.scores[0].total, result.scores[0].largest_domain, result.scores[0].crowns) == (
        2,
        2,
        1,
    )
    assert result.scores[1].total == 0
    # 完全相同则共同获胜。
    tie = score_kingdoms(
        (kingdom("pink", cell(1, 0, "field", 2)), kingdom("yellow", cell(1, 0, "field", 2)))
    )
    assert tie.winner_seat_ids == ("pink", "yellow")


def test_full_game_ends_with_scores():
    rules = engine(7)
    state = rules.initialize(KingdominoConfig(), ("pink", "yellow"))
    steps = 0
    while state.phase != "finished":
        state = take(rules, state)
        steps += 1
        assert steps < 200
    assert state.result is not None and state.result.reason == "scored"
    assert len(state.result.scores) == 2
    # 每张地块两格，已放格数的一半即已放地块数；其余地块都进了弃置堆。
    placed_dominoes = sum(len(item.cells) - 1 for item in state.kingdoms) // 2
    assert placed_dominoes + len(state.discarded) == 24
    assert rules.observe(state, "pink").current_seat_id is None
    assert_error("game_finished", rules.apply, state, "pink", DiscardDominoAction())


def test_state_round_trips_through_json():
    rules = engine(11)
    state = rules.initialize(KingdominoConfig(), ("pink", "yellow", "green"))
    while state.phase == "seeding":
        state = take(rules, state)
    state = take(rules, state)
    assert KingdominoState.model_validate_json(state.model_dump_json()) == state


def test_resign_is_not_supported():
    rules = engine()
    state = rules.initialize(KingdominoConfig(), ("pink", "yellow"))
    assert_error("operation_not_supported", rules.resign, state, "pink")
