from typing import Literal

from pydantic import Field

from echo_games.aeroplane.board import SeatId
from echo_games.aeroplane.models import (
    AeroplaneAction,
    AeroplaneActionOutcome,
    AeroplaneConfig,
    AeroplaneResult,
    AeroplaneState,
)
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


class AeroplaneCreateGameCommand(CreateGameCommand[AeroplaneConfig]):
    game_type: Literal["aeroplane"] = "aeroplane"
    ruleset_id: Literal["aeroplane.traditional"] = "aeroplane.traditional"
    ruleset_version: int = Field(default=1, ge=1)
    initial_seat_id: SeatId = "red"
    config: AeroplaneConfig = Field(default_factory=AeroplaneConfig)


AeroplaneGame = Game[AeroplaneConfig, AeroplaneState]
AeroplaneSubmitActionCommand = SubmitActionCommand[AeroplaneAction]
AeroplaneSummary = GameSummary[AeroplaneConfig, AeroplaneResult]
AeroplaneView = GameView[AeroplaneState, AeroplaneAction]
AeroplaneOpportunity = ActionOpportunity[AeroplaneAction]
AeroplaneDecisionInput = DecisionInput[AeroplaneState, AeroplaneAction]
AeroplaneActionReceipt = ActionReceipt[AeroplaneActionOutcome]
AeroplaneOperationReceipt = GameOperationReceipt[AeroplaneResult]
AeroplaneEvent = GameEvent[AeroplaneActionOutcome, AeroplaneResult]
AeroplaneEventBatch = GameEventBatch[AeroplaneActionOutcome, AeroplaneResult]

AEROPLANE_MODELS = GameModels[
    AeroplaneConfig,
    AeroplaneState,
    AeroplaneState,
    AeroplaneAction,
    AeroplaneActionOutcome,
    AeroplaneResult,
    AeroplaneActionOutcome,
](
    game=AeroplaneGame,
    create_command=AeroplaneCreateGameCommand,
    action_command=AeroplaneSubmitActionCommand,
    summary=AeroplaneSummary,
    ruleset_view=RulesetView[AeroplaneConfig],
    view=AeroplaneView,
    opportunity=AeroplaneOpportunity,
    decision_input=AeroplaneDecisionInput,
    action_receipt=AeroplaneActionReceipt,
    operation_receipt=AeroplaneOperationReceipt,
    event=AeroplaneEvent,
    event_batch=AeroplaneEventBatch,
    finished_event=GameFinished[AeroplaneResult],
    resigned_result=ResignedResult[AeroplaneResult],
)
