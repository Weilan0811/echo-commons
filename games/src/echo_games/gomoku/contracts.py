from typing import Literal

from pydantic import Field

from echo_games.contracts import (
    ActionOpportunity,
    ActionReceipt,
    CreateGameCommand,
    DecisionInput,
    GameEvent,
    GameEventBatch,
    GameFinished,
    GameModels,
    GameOperationReceipt,
    GameSummary,
    GameView,
    ResignedResult,
    RulesetView,
    SubmitActionCommand,
)
from echo_games.domain import Game
from echo_games.gomoku.models import (
    GomokuConfig,
    GomokuResult,
    GomokuState,
    PlaceStoneAction,
    StonePlacedResult,
)


class GomokuCreateGameCommand(CreateGameCommand[GomokuConfig]):
    game_type: Literal["gomoku"] = "gomoku"
    ruleset_id: Literal["gomoku.freestyle"] = "gomoku.freestyle"
    ruleset_version: int = Field(default=1, ge=1)
    initial_seat_id: Literal["black", "white"] = "black"
    config: GomokuConfig = Field(default_factory=GomokuConfig)


GomokuGame = Game[GomokuConfig, GomokuState]
GomokuSubmitActionCommand = SubmitActionCommand[PlaceStoneAction]
GomokuSummary = GameSummary[GomokuConfig, GomokuResult]
GomokuView = GameView[GomokuState, PlaceStoneAction]
GomokuOpportunity = ActionOpportunity[PlaceStoneAction]
GomokuDecisionInput = DecisionInput[GomokuState, PlaceStoneAction]
GomokuActionReceipt = ActionReceipt[StonePlacedResult]
GomokuOperationReceipt = GameOperationReceipt[GomokuResult]
GomokuEvent = GameEvent[StonePlacedResult, GomokuResult]
GomokuEventBatch = GameEventBatch[StonePlacedResult, GomokuResult]

GOMOKU_MODELS = GameModels[
    GomokuConfig,
    GomokuState,
    GomokuState,
    PlaceStoneAction,
    StonePlacedResult,
    GomokuResult,
    StonePlacedResult,
](
    game=GomokuGame,
    create_command=GomokuCreateGameCommand,
    action_command=GomokuSubmitActionCommand,
    summary=GomokuSummary,
    ruleset_view=RulesetView[GomokuConfig],
    view=GomokuView,
    opportunity=GomokuOpportunity,
    decision_input=GomokuDecisionInput,
    action_receipt=GomokuActionReceipt,
    operation_receipt=GomokuOperationReceipt,
    event=GomokuEvent,
    event_batch=GomokuEventBatch,
    finished_event=GameFinished[GomokuResult],
    resigned_result=ResignedResult[GomokuResult],
)
