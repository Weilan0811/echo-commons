from pydantic import BaseModel, ConfigDict

from echo_games.errors import GameError
from echo_games.gomoku.contracts import GomokuView
from echo_games.gomoku.models import GomokuResult, PlaceStoneAction
from echo_games.gomoku.rules import GomokuRules


class GomokuTactics(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    winning_actions: tuple[PlaceStoneAction, ...]
    opponent_winning_actions: tuple[PlaceStoneAction, ...]


class GomokuActionPreview(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    action: PlaceStoneAction
    result: GomokuResult | None
    own_winning_threats: tuple[PlaceStoneAction, ...]
    opponent_winning_actions: tuple[PlaceStoneAction, ...]


def read_gomoku_tactics(view: GomokuView) -> GomokuTactics:
    if (view.game_type, view.ruleset_id, view.ruleset_version) != ("gomoku", "gomoku.freestyle", 1):
        raise GameError("unsupported_ruleset", "Gomoku preview requires freestyle version 1")
    if view.status != "running" or view.state.current_seat_id != view.viewer_seat_id:
        raise GameError("not_current_actor", "Only the current actor can preview actions")
    rules = GomokuRules()
    opponent = "white" if view.viewer_seat_id == "black" else "black"
    return GomokuTactics(
        winning_actions=rules.winning_actions(view.state, view.viewer_seat_id),
        opponent_winning_actions=rules.winning_actions(view.state, opponent),
    )


def preview_gomoku_actions(
    view: GomokuView, actions: tuple[PlaceStoneAction, ...]
) -> tuple[GomokuActionPreview, ...]:
    read_gomoku_tactics(view)
    rules = GomokuRules()
    opponent = "white" if view.viewer_seat_id == "black" else "black"
    previews = []
    for action in actions:
        after = rules.apply(view.state, view.viewer_seat_id, action).state
        previews.append(
            GomokuActionPreview(
                action=action,
                result=after.result,
                own_winning_threats=rules.winning_actions(after, view.viewer_seat_id),
                opponent_winning_actions=rules.winning_actions(after, opponent),
            )
        )
    return tuple(previews)
