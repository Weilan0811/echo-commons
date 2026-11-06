from time import perf_counter

from echo_games.public import (
    AeroplaneAction,
    AeroplaneView,
    aeroplane_plane_progress,
    preview_aeroplane_actions,
    read_aeroplane_capture_opportunities,
)
from pydantic import TypeAdapter

from echo_commons.modules.activities.gameplay.contracts import (
    ActionCandidate,
    AnalysisRun,
    GameplayAnalysis,
    GameplayAnalysisError,
    RuleFact,
    SearchEstimate,
)

ACTION = TypeAdapter(AeroplaneAction)
WEIGHTS = {"arrived": 4.0, "progress": 1.0, "deployment": 0.25, "attack": 0.8, "risk": -1.2}


def candidate_id(action):
    plane = getattr(action, "plane_id", None)
    return action.type if plane is None else f"{action.type}:{plane}"


def position(state, seat):
    values = [aeroplane_plane_progress(p) for p in state.planes if p.seat_id == seat]
    return {
        "arrived": sum(v == 1 for v in values),
        "progress": sum(values),
        "deployment": sum(v > 0 for v in values),
    }


def risk(state, seat):
    progress = {p.plane_id: aeroplane_plane_progress(p) for p in state.planes if p.seat_id == seat}
    losses = {}
    for opportunity in read_aeroplane_capture_opportunities(state, seat):
        key = opportunity.opponent_seat_id, opportunity.dice
        losses[key] = max(losses.get(key, 0), sum(progress[i] for i in opportunity.plane_ids))
    return max(
        (
            sum(losses.get((opponent, dice), 0) for dice in range(1, 7)) / 6
            for opponent in state.seat_order
            if opponent != seat
        ),
        default=0,
    )


class AeroplaneAnalyzer:
    action_model = AeroplaneAction
    game_type = "aeroplane"
    ruleset_id = "aeroplane.traditional"
    ruleset_version = 1

    def reaction_significance(self, view, previous, analyses=()):
        if previous is None:
            return 0
        current = AeroplaneView.model_validate(view.model_dump())
        old = AeroplaneView.model_validate(previous)
        before = {(p.seat_id, p.plane_id): p for p in old.state.planes}
        importance = 0.0
        for plane in current.state.planes:
            prior = before[plane.seat_id, plane.plane_id]
            if prior.step is not None and plane.step is None:
                importance = max(importance, 0.8)
            elif aeroplane_plane_progress(plane) == 1 and aeroplane_plane_progress(prior) < 1:
                importance = max(importance, 0.7)
        if current.state.phase == "awaiting_penalty" and old.state.phase != "awaiting_penalty":
            importance = max(importance, 0.7)
        return importance

    async def analyze(self, request):
        started = perf_counter()
        view = AeroplaneView.model_validate(request.view.model_dump())
        legal = tuple(
            ACTION.validate_python(a.model_dump()) for a in request.opportunity.legal_actions
        )
        suggestions = tuple(
            ACTION.validate_python(a.model_dump()) for a in request.suggested_actions
        )
        if any(action not in legal for action in suggestions):
            raise GameplayAnalysisError("illegal_suggestion", "Suggested actions must be legal")
        seat = view.viewer_seat_id
        before = position(view.state, seat)
        opponent_before = sum(
            aeroplane_plane_progress(p) for p in view.state.planes if p.seat_id != seat
        )
        risk_cache = {}
        candidates = []
        ranks = {}
        for preview in preview_aeroplane_actions(view, legal):
            evaluated = []
            for branch in preview.branches:
                after = position(branch.state, seat)
                if branch.state.planes not in risk_cache:
                    risk_cache[branch.state.planes] = risk(branch.state, seat)
                terms = {name: after[name] - before[name] for name in before}
                terms["attack"] = opponent_before - sum(
                    aeroplane_plane_progress(p) for p in branch.state.planes if p.seat_id != seat
                )
                terms["risk"] = risk_cache[branch.state.planes]
                wins = (
                    branch.state.result is not None and branch.state.result.winner_seat_id == seat
                )
                score = sum(WEIGHTS[name] * value for name, value in terms.items())
                evaluated.append((wins, score, branch, terms))
            wins, score, branch, terms = max(evaluated, key=lambda item: item[:2])
            identity = candidate_id(preview.action)
            ranks[identity] = wins, score
            facts = (
                (
                    RuleFact(
                        code="immediate_outcome",
                        description="执行当前动作的确定事件；后续跳跃仍需正式选择并执行。",
                        details={
                            "events": [e.model_dump(mode="json") for e in preview.immediate.events],
                            "phase": preview.immediate.state.phase,
                            "result": (
                                preview.immediate.state.result.model_dump(mode="json")
                                if preview.immediate.state.result
                                else None
                            ),
                        },
                    ),
                )
                if preview.immediate
                else (
                    RuleFact(
                        code="random_roll", description="正式执行时随机掷骰，一至六点各为六分之一。"
                    ),
                )
            )
            estimates = (
                ()
                if preview.immediate is None
                else (
                    SearchEstimate[AeroplaneAction](
                        source="aeroplane.rules",
                        scale="aeroplane.utility.v1",
                        value=score,
                        continuation=branch.continuation,
                        details={
                            "components": terms,
                            "weights": WEIGHTS,
                            "wins_with_continuation": wins,
                            "meaning": "按所列后续选择计算的固定策略评分，不代表获胜概率。",
                            "risk_scope": "棋盘不变时各对手独立掷骰一次，取最大平均可捕获进度损失；"
                            "包含跳跃与捷径，不含追加掷骰或其他行动者改变棋盘。",
                        },
                    ),
                )
            )
            candidates.append(
                ActionCandidate[AeroplaneAction](
                    candidate_id=identity,
                    action=preview.action,
                    origins=("rule", "suggestion") if preview.action in suggestions else ("rule",),
                    facts=facts,
                    estimates=estimates,
                )
            )
        return GameplayAnalysis[AeroplaneAction](
            game_id=view.game_id,
            game_type=view.game_type,
            ruleset_id=view.ruleset_id,
            ruleset_version=view.ruleset_version,
            state_version=view.state_version,
            participation_id=view.viewer_participation_id,
            opportunity_id=request.opportunity.opportunity_id,
            legal_action_count=len(legal),
            choice_required=len(legal) > 1,
            candidates=tuple(candidates),
            recommended_candidate_id=max(ranks, key=ranks.__getitem__),
            runs=(
                AnalysisRun(
                    analyzer="aeroplane.rules",
                    version="1",
                    resources={
                        "elapsed_ms": (perf_counter() - started) * 1000,
                        "candidate_count": len(legal),
                    },
                ),
            ),
        )
