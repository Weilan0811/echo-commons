import random

import pytest

from echo_games.aeroplane.contracts import AeroplaneOpportunity
from echo_games.aeroplane.rules import AeroplaneRules
from echo_games.public import (
    AeroplaneState,
    AeroplaneView,
    GameError,
    MovePlaneAction,
    Plane,
    RollDiceAction,
    preview_aeroplane_actions,
    read_aeroplane_capture_opportunities,
)


def view_for(on_board, **changes):
    state = AeroplaneState(
        seat_order=("red", "yellow"),
        planes=tuple(
            Plane(seat_id=seat, plane_id=i, step=on_board.get(seat, {}).get(i))
            for seat in ("red", "yellow")
            for i in range(1, 5)
        ),
        **{"phase": "awaiting_action", "dice": 4, **changes},
    )
    actions = AeroplaneRules().legal_actions(state, "red")
    opportunity = AeroplaneOpportunity(
        opportunity_id="opportunity",
        game_id="game",
        seat_id="red",
        participation_id="red-player",
        expected_state_version=3,
        phase=state.phase,
        choice_required=len(actions) > 1,
        legal_actions=actions,
    )
    return AeroplaneView(
        game_id="game",
        game_type="aeroplane",
        ruleset_id="aeroplane.traditional",
        ruleset_version=1,
        state_version=3,
        status="running",
        phase=state.phase,
        viewer_seat_id="red",
        viewer_participation_id="red-player",
        state=state,
        opportunities=(opportunity,),
    )


def test_preview_keeps_immediate_capture_and_optional_chain_separate():
    view = view_for({"red": {1: 8}, "yellow": {1: 51 - 13, 2: 3}})
    original = view.model_dump_json()
    (preview,) = preview_aeroplane_actions(view, (MovePlaneAction(plane_id=1),))
    assert preview.immediate.state.phase == "awaiting_chain"
    assert {tuple(a.type for a in b.continuation) for b in preview.branches} == {
        ("end_move",),
        ("jump_four", "end_move"),
        ("jump_four", "fly_shortcut"),
    }
    assert any(
        e.type == "plane_sent_back" and e.plane_id == 2 for b in preview.branches for e in b.events
    )
    assert view.model_dump_json() == original


def test_roll_enumeration_preserves_sixes_penalty_and_real_random_source():
    source = random.Random(21)
    rules = AeroplaneRules(source)
    view = view_for({"red": {1: 20}}, phase="awaiting_roll", dice=None, consecutive_sixes=2)
    initial_random = source.getstate()
    (preview,) = preview_aeroplane_actions(view, (RollDiceAction(),))
    assert [b.dice for b in preview.branches] == [1, 2, 3, 4, 5, 6]
    assert preview.branches[-1].state.phase == "awaiting_penalty"
    assert source.getstate() == initial_random
    actual = rules.apply(view.state, "red", RollDiceAction())
    branch = next(b for b in preview.branches if b.dice == actual.result.dice)
    assert branch.state == actual.state and branch.events == actual.events


def test_threats_include_shortcuts_and_exclude_waiting_and_home_planes():
    # 黄步 12 + 四点到捷径，再飞到步 28，对应红步 41。
    view = view_for({"red": {1: 41, 2: -1, 3: 55}, "yellow": {1: 12}})
    threats = read_aeroplane_capture_opportunities(view.state, "red")
    assert any(t.dice == 4 and t.plane_ids == (1,) for t in threats)
    assert all(2 not in t.plane_ids and 3 not in t.plane_ids for t in threats)
    with pytest.raises(GameError, match="legal"):
        preview_aeroplane_actions(view, (MovePlaneAction(plane_id=4),))


def test_preview_home_bounce_and_penalty_use_the_game_rules():
    view = view_for({"red": {1: 54, 2: 55, 3: 55, 4: 55}})
    (bounce,) = preview_aeroplane_actions(view, (MovePlaneAction(plane_id=1),))
    assert bounce.immediate.state.planes[0].step == 52
    finish = view_for({"red": {1: 54, 2: 55, 3: 55, 4: 55}}, dice=1)
    (won,) = preview_aeroplane_actions(finish, (MovePlaneAction(plane_id=1),))
    assert won.immediate.state.result.winner_seat_id == "red"
    penalty = view_for(
        {"red": {1: 20, 2: 5}}, phase="awaiting_penalty", dice=6, consecutive_sixes=3
    )
    previews = preview_aeroplane_actions(penalty, penalty.opportunities[0].legal_actions)
    assert all(p.immediate.state.current_seat_id == "yellow" for p in previews)
    assert all(p.immediate.events[0].reason == "penalty" for p in previews)
