from echo_games.public import (
    GomokuActionPreview,
    GomokuView,
    PlaceStoneAction,
    preview_gomoku_actions,
    read_gomoku_tactics,
)

from echo_commons.infrastructure.game_analysis.rapfi.contracts import RapfiError
from echo_commons.infrastructure.game_analysis.rapfi.process import RapfiProcess
from echo_commons.modules.activities.gameplay.contracts import (
    ActionCandidate,
    AnalysisRequest,
    AnalysisRun,
    GameplayAnalysis,
    GameplayAnalysisError,
    RuleFact,
    SearchEstimate,
)


def candidate_id(action: PlaceStoneAction) -> str:
    return f"place:{action.x}:{action.y}"


def rule_facts(preview: GomokuActionPreview, *, blocks_win: bool) -> tuple[RuleFact, ...]:
    facts = []
    if preview.result is not None:
        facts.append(
            RuleFact(
                code="wins_now" if preview.result.winner_seat_id else "draws_now",
                description="落下这一步立即获胜。"
                if preview.result.winner_seat_id
                else "落下这一步棋盘已满，和局。",
                details=preview.result.model_dump(mode="json"),
            )
        )
    else:
        facts.extend(
            (
                RuleFact(
                    code="opponent_winning_replies",
                    description="落子后，对手下一手能够立即获胜的位置；空列表表示没有这样的落点。",
                    details={
                        "actions": [
                            a.model_dump(mode="json") for a in preview.opponent_winning_actions
                        ]
                    },
                ),
                RuleFact(
                    code="own_winning_threats",
                    description="落子后，己方再落一子即可获胜的位置；对手仍能在下一手改变局面。",
                    details={
                        "actions": [a.model_dump(mode="json") for a in preview.own_winning_threats]
                    },
                ),
            )
        )
    if blocks_win:
        facts.append(
            RuleFact(
                code="blocks_winning_point",
                description="占据对手原本可立即获胜的位置；其他威胁见后续合法回应。",
            )
        )
    return tuple(facts)


class GomokuAnalyzer:
    action_model = PlaceStoneAction
    game_type = "gomoku"
    ruleset_id = "gomoku.freestyle"
    ruleset_version = 1

    def __init__(self, engine: RapfiProcess):
        self.engine = engine

    async def analyze(self, request: AnalysisRequest) -> GameplayAnalysis[PlaceStoneAction]:
        view = GomokuView.model_validate(request.view.model_dump(mode="python"))
        opportunity = request.opportunity
        legal = tuple(
            PlaceStoneAction.model_validate(a.model_dump()) for a in opportunity.legal_actions
        )
        suggestions = tuple(
            PlaceStoneAction.model_validate(a.model_dump()) for a in request.suggested_actions
        )
        if any(action not in legal for action in suggestions):
            raise GameplayAnalysisError(
                "illegal_suggestion", "Suggested actions must be legal in this observation"
            )
        tactics = read_gomoku_tactics(view)
        required = tuple(
            dict.fromkeys(
                (*tactics.winning_actions, *tactics.opponent_winning_actions, *suggestions)
            )
        )
        limit = self.engine.settings.candidates
        # 必须展示的真实建议和直接战术超出预算时明确失败，避免悄悄丢失依据。
        if len(required) > limit:
            raise GameplayAnalysisError(
                "candidate_budget_exceeded",
                "Required candidates exceed the configured candidate budget",
            )
        stones = tuple(
            (s.x, s.y, 1 if s.seat_id == view.viewer_seat_id else 2) for s in view.state.stones
        )
        budget = self.engine.settings.search_time_ms
        first_budget = max(10, budget * 3 // 4) if suggestions else budget
        try:
            primary = await self.engine.analyze(stones, candidates=limit, time_ms=first_budget)
            runs = [primary]
            estimates = {}
            for line in primary.lines:
                previous = estimates.get(line.moves[0])
                if previous is None or (line.depth, line.time_ms) > (
                    previous.depth,
                    previous.time_ms,
                ):
                    estimates[line.moves[0]] = line
            missing = tuple(a for a in suggestions if (a.x, a.y) not in estimates)
            if missing and budget - first_budget >= 10:
                allowed = {(a.x, a.y) for a in missing}
                extra = await self.engine.analyze(
                    stones,
                    candidates=len(allowed),
                    time_ms=budget - first_budget,
                    blocked=tuple((a.x, a.y) for a in legal if (a.x, a.y) not in allowed),
                )
                runs.append(extra)
                estimates.update({line.moves[0]: line for line in extra.lines})
        except RapfiError as error:
            raise GameplayAnalysisError(
                error.code,
                str(error),
                retryable=error.code in ("process_exited", "analysis_timeout", "analysis_failed"),
            ) from error
        best = PlaceStoneAction(x=primary.best_move[0], y=primary.best_move[1])
        engine_actions = tuple(
            PlaceStoneAction(x=line.moves[0][0], y=line.moves[0][1]) for line in primary.lines
        )
        if any(a not in legal for a in (best, *engine_actions)):
            raise GameplayAnalysisError(
                "illegal_analysis", "Rapfi returned an action outside this opportunity"
            )
        selected = tuple(dict.fromkeys((*required, best, *engine_actions)))
        if len(required) == limit and best not in required:
            raise GameplayAnalysisError(
                "candidate_budget_exceeded", "No room for the engine reference action"
            )
        selected = selected[:limit]
        candidates = []
        for preview in preview_gomoku_actions(view, selected):
            action = preview.action
            origins = tuple(
                name
                for name, included in (
                    (
                        "rule",
                        action in (*tactics.winning_actions, *tactics.opponent_winning_actions),
                    ),
                    ("suggestion", action in suggestions),
                    ("engine", action == best or action in engine_actions),
                )
                if included
            )
            line = estimates.get((action.x, action.y))
            scale, value, score_details = "rapfi.raw", 0, {}
            if line is not None:
                if isinstance(line.score, str):
                    sign = 1 if line.score.startswith("+") else -1
                    scale = "rapfi.forced_outcome"
                    value = sign
                    score_details = {
                        "raw_score": line.score,
                        "mate_plies": None if line.score[2:] == "*" else int(line.score[2:]),
                        "meaning": "引擎预测强制胜负：1 为当前行动方获胜，-1 为失利；"
                        "mate_plies 是从当前局面起的落子次数。正式胜负仍由游戏规则确定。",
                    }
                else:
                    value = line.score
            candidate_estimates = (
                ()
                if line is None
                else (
                    SearchEstimate[PlaceStoneAction](
                        source="rapfi",
                        scale=scale,
                        value=value,
                        continuation=tuple(PlaceStoneAction(x=x, y=y) for x, y in line.moves),
                        details={
                            "depth": line.depth,
                            "nodes": line.nodes,
                            "time_ms": line.time_ms,
                            **score_details,
                        },
                    ),
                )
            )
            candidates.append(
                ActionCandidate[PlaceStoneAction](
                    candidate_id=candidate_id(action),
                    action=action,
                    origins=origins,
                    facts=rule_facts(
                        preview, blocks_win=action in tactics.opponent_winning_actions
                    ),
                    estimates=candidate_estimates,
                )
            )
        return GameplayAnalysis[PlaceStoneAction](
            game_id=view.game_id,
            game_type=view.game_type,
            ruleset_id=view.ruleset_id,
            ruleset_version=view.ruleset_version,
            state_version=view.state_version,
            participation_id=view.viewer_participation_id,
            opportunity_id=opportunity.opportunity_id,
            legal_action_count=len(legal),
            choice_required=len(legal) > 1,
            candidates=tuple(candidates),
            recommended_candidate_id=candidate_id(best),
            runs=tuple(
                AnalysisRun(
                    analyzer="rapfi",
                    version=run.engine_version,
                    resources={
                        "release": run.release,
                        "weight": run.weight,
                        "budget_ms": run.budget_ms,
                        "elapsed_ms": run.elapsed_ms,
                        "threads": run.threads,
                        "hash_memory_mb": run.hash_memory_mb,
                    },
                )
                for run in runs
            ),
        )
