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
from echo_games.kingdomino.models import (
    KingdominoAction,
    KingdominoActionOutcome,
    KingdominoBoard,
    KingdominoConfig,
    KingdominoResult,
    KingdominoState,
    SeatId,
)


class KingdominoCreateGameCommand(CreateGameCommand[KingdominoConfig]):
    game_type: Literal["kingdomino"] = "kingdomino"
    ruleset_id: Literal["kingdomino.classic"] = "kingdomino.classic"
    ruleset_version: int = Field(default=1, ge=1)
    initial_seat_id: SeatId = "pink"
    config: KingdominoConfig = Field(default_factory=KingdominoConfig)


KingdominoGame = Game[KingdominoConfig, KingdominoState]
KingdominoSubmitActionCommand = SubmitActionCommand[KingdominoAction]
KingdominoSummary = GameSummary[KingdominoConfig, KingdominoResult]
KingdominoView = GameView[KingdominoBoard, KingdominoAction]
KingdominoOpportunity = ActionOpportunity[KingdominoAction]
KingdominoDecisionInput = DecisionInput[KingdominoBoard, KingdominoAction]
KingdominoActionReceipt = ActionReceipt[KingdominoActionOutcome]
KingdominoOperationReceipt = GameOperationReceipt[KingdominoResult]
KingdominoEvent = GameEvent[KingdominoActionOutcome, KingdominoResult]
KingdominoEventBatch = GameEventBatch[KingdominoActionOutcome, KingdominoResult]

KINGDOMINO_MODELS = GameModels[
    KingdominoConfig,
    KingdominoState,
    KingdominoBoard,
    KingdominoAction,
    KingdominoActionOutcome,
    KingdominoResult,
    KingdominoActionOutcome,
](
    game=KingdominoGame,
    create_command=KingdominoCreateGameCommand,
    action_command=KingdominoSubmitActionCommand,
    summary=KingdominoSummary,
    ruleset_view=RulesetView[KingdominoConfig],
    view=KingdominoView,
    opportunity=KingdominoOpportunity,
    decision_input=KingdominoDecisionInput,
    action_receipt=KingdominoActionReceipt,
    operation_receipt=KingdominoOperationReceipt,
    event=KingdominoEvent,
    event_batch=KingdominoEventBatch,
    finished_event=GameFinished[KingdominoResult],
    resigned_result=ResignedResult[KingdominoResult],
)
