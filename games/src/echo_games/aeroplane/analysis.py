from typing import cast

from pydantic import BaseModel, ConfigDict

from echo_games.aeroplane.board import HOME_STEP, SeatId
from echo_games.aeroplane.contracts import AeroplaneView
from echo_games.aeroplane.models import (
    AeroplaneAction,
    AeroplaneActionOutcome,
    AeroplaneState,
    Dice,
    Plane,
    PlaneSentBack,
    RollDiceAction,
)
from echo_games.aeroplane.rules import AeroplaneRules
from echo_games.errors import GameError


class AeroplaneBranch(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    continuation: tuple[AeroplaneAction, ...] = ()
    state: AeroplaneState
    events: tuple[AeroplaneActionOutcome, ...]
    dice: Dice | None = None


class AeroplaneActionPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: AeroplaneAction
    immediate: AeroplaneBranch | None
    branches: tuple[AeroplaneBranch, ...]


class AeroplaneCaptureOpportunity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    opponent_seat_id: SeatId
    dice: Dice
    plane_ids: tuple[int, ...]


def aeroplane_plane_progress(plane: Plane) -> float:
    return 0.0 if plane.step is None else (plane.step + 2) / (HOME_STEP + 2)


def _finish_chains(rules, state, seat_id, events, continuation=()):
    if state.phase != "awaiting_chain" or state.current_seat_id != seat_id:
        return (AeroplaneBranch(state=state, events=events, continuation=continuation),)
    return tuple(
        branch
        for action in rules.legal_actions(state, seat_id)
        for transition in (rules.apply(state, seat_id, action),)
        for branch in _finish_chains(
            rules, transition.state, seat_id, events + transition.events, continuation + (action,)
        )
    )


def preview_aeroplane_actions(
    view: AeroplaneView, actions: tuple[AeroplaneAction, ...]
) -> tuple[AeroplaneActionPreview, ...]:
    if (view.game_type, view.ruleset_id, view.ruleset_version) != (
        "aeroplane",
        "aeroplane.traditional",
        1,
    ):
        raise GameError("unsupported_ruleset", "Aeroplane preview requires traditional version 1")
    rules = AeroplaneRules()
    legal = rules.legal_actions(view.state, view.viewer_seat_id) if view.status == "running" else ()
    if not legal:
        raise GameError("not_current_actor", "Only the current actor can preview actions")
    previews = []
    for action in actions:
        if action not in legal:
            raise GameError("illegal_action", "Preview action must be legal in this observation")
        if isinstance(action, RollDiceAction):
            branches = []
            for dice in (1, 2, 3, 4, 5, 6):
                transition = rules.resolve_roll(view.state, view.viewer_seat_id, dice)
                branches.append(
                    AeroplaneBranch(state=transition.state, events=transition.events, dice=dice)
                )
            previews.append(
                AeroplaneActionPreview(action=action, immediate=None, branches=tuple(branches))
            )
        else:
            transition = rules.apply(view.state, view.viewer_seat_id, action)
            previews.append(
                AeroplaneActionPreview(
                    action=action,
                    immediate=AeroplaneBranch(state=transition.state, events=transition.events),
                    branches=_finish_chains(
                        rules, transition.state, view.viewer_seat_id, transition.events
                    ),
                )
            )
    return tuple(previews)


def read_aeroplane_capture_opportunities(
    state: AeroplaneState, seat_id: str
) -> tuple[AeroplaneCaptureOpportunity, ...]:
    if state.result is not None:
        return ()
    rules = AeroplaneRules()
    opportunities = []
    # 各对手在棋盘保持不变时独立投骰一次；不将这些条件机会当作整轮返航概率。
    for opponent in state.seat_order:
        if opponent == seat_id:
            continue
        before_roll = state.model_copy(
            update={
                "current_seat_id": opponent,
                "phase": "awaiting_roll",
                "dice": None,
                "consecutive_sixes": 0,
                "pending_plane_id": None,
                "pending_arrival": None,
            }
        )
        for dice in (1, 2, 3, 4, 5, 6):
            rolled = rules.resolve_roll(before_roll, opponent, cast(Dice, dice)).state
            if rolled.phase != "awaiting_action" or rolled.current_seat_id != opponent:
                continue
            captures = set()
            for action in rules.legal_actions(rolled, opponent):
                transition = rules.apply(rolled, opponent, action)
                for branch in _finish_chains(rules, transition.state, opponent, transition.events):
                    captured = tuple(
                        sorted(
                            event.plane_id
                            for event in branch.events
                            if isinstance(event, PlaneSentBack)
                            and event.seat_id == seat_id
                            and event.reason == "captured"
                        )
                    )
                    if captured:
                        captures.add(captured)
            opportunities.extend(
                AeroplaneCaptureOpportunity(opponent_seat_id=opponent, dice=dice, plane_ids=planes)
                for planes in sorted(captures)
            )
    return tuple(opportunities)
