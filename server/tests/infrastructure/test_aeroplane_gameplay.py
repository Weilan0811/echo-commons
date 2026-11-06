import pytest
from echo_games.aeroplane.contracts import AeroplaneOpportunity
from echo_games.aeroplane.rules import AeroplaneRules
from echo_games.public import AeroplaneAction, AeroplaneState, AeroplaneView, Plane, TakeOffAction

from echo_commons.modules.activities.gameplay.aeroplane import AeroplaneAnalyzer
from echo_commons.modules.activities.gameplay.contracts import (
    AnalysisRequest,
    GameplayAnalysis,
    GameplayAnalysisError,
)
from echo_commons.modules.activities.gameplay.registry import GameplayRegistry


def request_for(steps, **changes):
    state = AeroplaneState(
        seat_order=("red", "yellow"),
        planes=tuple(
            Plane(seat_id=seat, plane_id=i, step=steps.get(seat, {}).get(i))
            for seat in ("red", "yellow")
            for i in range(1, 5)
        ),
        **{"phase": "awaiting_action", "dice": 1, **changes},
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
    return AnalysisRequest(
        view=AeroplaneView(
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
        ),
        opportunity=opportunity,
    )


@pytest.mark.asyncio
async def test_all_actions_round_trip_and_prefer_finishing_with_explained_scores():
    registry = GameplayRegistry((AeroplaneAnalyzer(),))
    request = request_for({"red": {1: 54, 2: 10}})
    analysis = await registry.analyze(request)
    assert len(analysis.candidates) == analysis.legal_action_count == 2
    assert analysis.recommended_candidate_id == "move_plane:1"
    assert (
        GameplayAnalysis[AeroplaneAction].model_validate_json(analysis.model_dump_json())
        == analysis
    )
    assert all(c.estimates[0].details["components"] for c in analysis.candidates)
    repeated = await registry.analyze(request)
    assert repeated.candidates == analysis.candidates
    suggestion = request.model_copy(update={"suggested_actions": (TakeOffAction(plane_id=4),)})
    with pytest.raises(GameplayAnalysisError, match="legal"):
        await registry.analyze(suggestion)


@pytest.mark.asyncio
async def test_penalty_recommends_losing_less_progress_and_reactions_detect_return():
    analyzer = AeroplaneAnalyzer()
    request = request_for(
        {"red": {1: 40, 2: 1}}, phase="awaiting_penalty", dice=6, consecutive_sixes=3
    )
    analysis = await GameplayRegistry((analyzer,)).analyze(request)
    assert analysis.recommended_candidate_id == "return_penalty:2"
    previous = request.view.model_dump(mode="json")
    current = request_for({"red": {1: 40}}).view
    assert analyzer.reaction_significance(current, previous) == 0.8
