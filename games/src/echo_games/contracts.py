from dataclasses import dataclass
from datetime import datetime
from typing import Annotated, Generic, Literal, Protocol, TypeVar

from pydantic import BaseModel, Field, JsonValue, SerializeAsAny

from echo_games.domain import (
    ConfigT,
    Game,
    GameModel,
    GameStatus,
    Identifier,
    Participation,
    StateT,
)

ViewT = TypeVar("ViewT", bound=BaseModel)
ActionT = TypeVar("ActionT", bound=BaseModel)
ActionResultT = TypeVar("ActionResultT", bound=BaseModel)
OutcomeT = TypeVar("OutcomeT", bound=BaseModel)


class GameEventData(GameModel):
    type: str


EventT = TypeVar("EventT", bound=GameEventData)


class GameInspectionRecord(GameModel):
    record_id: str
    position: int
    document: dict[str, JsonValue]
    command: dict[str, JsonValue] | None


class SeatAccess(GameModel):
    game_id: Identifier
    seat_id: Identifier
    participant_ref: Identifier
    participation_id: Identifier


class GameReadAccess(GameModel):
    game_id: Identifier
    requester_ref: Identifier


class CreateGameCommand(GameModel, Generic[ConfigT]):
    request_id: Identifier
    game_type: Identifier
    ruleset_id: Identifier
    ruleset_version: int = Field(ge=1)
    initial_seat_id: Identifier
    config: ConfigT


class JoinGameCommand(GameModel):
    game_id: Identifier
    request_id: Identifier
    expected_state_version: int = Field(ge=1)
    participant_ref: Identifier
    seat_id: Identifier


class LeaveGameCommand(GameModel):
    game_id: Identifier
    request_id: Identifier
    expected_state_version: int = Field(ge=1)
    participation_id: Identifier


class StartGameCommand(GameModel):
    game_id: Identifier
    request_id: Identifier
    expected_state_version: int = Field(ge=1)


class ResignGameCommand(GameModel):
    game_id: Identifier
    request_id: Identifier
    expected_state_version: int = Field(ge=1)
    participation_id: Identifier


class CancelGameCommand(GameModel):
    game_id: Identifier
    request_id: Identifier
    expected_state_version: int = Field(ge=1)
    reason: Identifier


class SubmitActionCommand(GameModel, Generic[ActionT]):
    request_id: Identifier
    opportunity_id: Identifier
    expected_state_version: int = Field(ge=1)
    action: ActionT


LifecycleCommand = (
    CreateGameCommand
    | JoinGameCommand
    | LeaveGameCommand
    | StartGameCommand
    | ResignGameCommand
    | CancelGameCommand
)


class GameSeat(GameModel):
    seat_id: Identifier
    occupant: Participation | None


class GameSummary(GameModel, Generic[ConfigT, OutcomeT]):
    game_id: Identifier
    game_type: Identifier
    ruleset_id: Identifier
    ruleset_version: int
    creator_ref: Identifier
    status: GameStatus
    state_version: int
    config: ConfigT
    seats: tuple[GameSeat, ...]
    result: OutcomeT | None
    cancel_reason: str | None
    created_at_utc: datetime
    updated_at_utc: datetime


class GameListQuery(GameModel):
    game_ids: tuple[Identifier, ...]
    game_type: Identifier | None = None
    status: GameStatus | None = None
    after_game_id: str = ""
    limit: int = Field(default=50, ge=1, le=200)


class GameSummaryBatch(GameModel):
    items: tuple[SerializeAsAny[GameSummary], ...]
    next_game_id: str
    has_more: bool


class ActionOpportunity(GameModel, Generic[ActionT]):
    opportunity_id: Identifier
    game_id: Identifier
    seat_id: Identifier
    participation_id: Identifier
    expected_state_version: int = Field(ge=1)
    phase: Identifier
    choice_required: bool
    legal_actions: tuple[ActionT, ...]


class OpenOpportunity(GameModel):
    opportunity_id: Identifier
    game_id: Identifier
    seat_id: Identifier
    participation_id: Identifier
    expected_state_version: int = Field(ge=1)
    phase: Identifier


class GameView(GameModel, Generic[ViewT, ActionT]):
    game_id: Identifier
    game_type: Identifier
    ruleset_id: Identifier
    ruleset_version: int
    state_version: int
    status: GameStatus
    phase: str
    viewer_seat_id: Identifier
    viewer_participation_id: Identifier
    state: ViewT
    opportunities: tuple[ActionOpportunity[ActionT], ...]


class DecisionInput(GameModel, Generic[ViewT, ActionT]):
    view: GameView[ViewT, ActionT]
    opportunity: ActionOpportunity[ActionT]
    instructions: str


class GameCreated(GameEventData):
    type: Literal["game_created"] = "game_created"
    creator_ref: Identifier
    game_type: Identifier
    ruleset_id: Identifier
    ruleset_version: int


class ParticipantJoined(GameEventData):
    type: Literal["participant_joined"] = "participant_joined"
    participation: Participation


class ParticipantLeft(GameEventData):
    type: Literal["participant_left"] = "participant_left"
    participation_id: Identifier
    seat_id: Identifier


class GameStarted(GameEventData):
    type: Literal["game_started"] = "game_started"
    participation_ids: tuple[Identifier, ...]


class ParticipantResigned(GameEventData):
    type: Literal["participant_resigned"] = "participant_resigned"
    participation_id: Identifier
    seat_id: Identifier


class GameFinished(GameEventData, Generic[OutcomeT]):
    type: Literal["game_finished"] = "game_finished"
    result: OutcomeT


class GameCancelled(GameEventData):
    type: Literal["game_cancelled"] = "game_cancelled"
    reason: str


class GameEvent(GameModel, Generic[EventT, OutcomeT]):
    event_id: Identifier
    game_id: Identifier
    sequence: int = Field(ge=1)
    state_version: int = Field(ge=1)
    occurred_at_utc: datetime
    type: str
    data: (
        GameCreated
        | ParticipantJoined
        | ParticipantLeft
        | GameStarted
        | ParticipantResigned
        | EventT
        | GameFinished[OutcomeT]
        | GameCancelled
    )


class GameEventBatch(GameModel, Generic[EventT, OutcomeT]):
    items: tuple[GameEvent[EventT, OutcomeT], ...]
    next_sequence: int = Field(ge=0)
    has_more: bool


class CreatedResult(GameModel):
    type: Literal["created"] = "created"
    participation: Participation


class JoinedResult(GameModel):
    type: Literal["joined"] = "joined"
    participation: Participation


class LeftResult(GameModel):
    type: Literal["left"] = "left"
    participation: Participation


class StartedResult(GameModel):
    type: Literal["started"] = "started"
    participation_ids: tuple[Identifier, ...]


class ResignedResult(GameModel, Generic[OutcomeT]):
    type: Literal["resigned"] = "resigned"
    participation_id: Identifier
    result: OutcomeT


class CancelledResult(GameModel):
    type: Literal["cancelled"] = "cancelled"
    reason: str


OperationResult = Annotated[
    CreatedResult
    | JoinedResult
    | LeftResult
    | StartedResult
    | ResignedResult[OutcomeT]
    | CancelledResult,
    Field(discriminator="type"),
]


OperationKind = Literal["create", "join", "leave", "start", "resign", "cancel"]


class GameOperationReceipt(GameModel, Generic[OutcomeT]):
    receipt_id: Identifier
    game_id: Identifier
    requester_ref: Identifier
    request_id: Identifier
    operation: OperationKind
    state_version_before: int = Field(ge=0)
    state_version_after: int = Field(ge=1)
    status_after: GameStatus
    result: OperationResult
    event_ids: tuple[Identifier, ...]
    occurred_at_utc: datetime


class ActionReceipt(GameModel, Generic[ActionResultT]):
    receipt_id: Identifier
    game_id: Identifier
    seat_id: Identifier
    participant_ref: Identifier
    participation_id: Identifier
    request_id: Identifier
    opportunity_id: Identifier
    status: Literal["applied"] = "applied"
    state_version_before: int = Field(ge=1)
    state_version_after: int = Field(ge=2)
    result: ActionResultT
    event_ids: tuple[Identifier, ...]
    occurred_at_utc: datetime


class RulesetView(GameModel, Generic[ConfigT]):
    ruleset_id: Identifier
    ruleset_version: int
    display_name: str
    min_players: int
    max_players: int
    config: ConfigT


class GameTypeView(GameModel):
    game_type: Identifier
    display_name: str
    rulesets: tuple[SerializeAsAny[RulesetView], ...]


class RuleTransition(GameModel, Generic[StateT, ActionResultT, EventT]):
    state: StateT
    result: ActionResultT
    events: tuple[EventT, ...]


@dataclass(frozen=True)
class GameModels(Generic[ConfigT, StateT, ViewT, ActionT, ActionResultT, OutcomeT, EventT]):
    game: type[Game[ConfigT, StateT]]
    create_command: type[CreateGameCommand[ConfigT]]
    action_command: type[SubmitActionCommand[ActionT]]
    summary: type[GameSummary[ConfigT, OutcomeT]]
    ruleset_view: type[RulesetView[ConfigT]]
    view: type[GameView[ViewT, ActionT]]
    opportunity: type[ActionOpportunity[ActionT]]
    decision_input: type[DecisionInput[ViewT, ActionT]]
    action_receipt: type[ActionReceipt[ActionResultT]]
    operation_receipt: type[GameOperationReceipt[OutcomeT]]
    event: type[GameEvent[EventT, OutcomeT]]
    event_batch: type[GameEventBatch[EventT, OutcomeT]]
    finished_event: type[GameFinished[OutcomeT]]
    resigned_result: type[ResignedResult[OutcomeT]]


class GameDefinition(Protocol[ConfigT, StateT, ViewT, ActionT, ActionResultT, OutcomeT, EventT]):
    game_type: str
    ruleset_id: str
    ruleset_version: int
    display_name: str
    ruleset_name: str
    seat_ids: tuple[str, ...]
    min_players: int
    max_players: int
    instructions: str
    default_config: ConfigT
    models: GameModels[ConfigT, StateT, ViewT, ActionT, ActionResultT, OutcomeT, EventT]

    def initialize(self, config: ConfigT) -> StateT: ...
    def observe(self, state: StateT, seat_id: str) -> ViewT: ...
    def phase(self, state: StateT) -> str: ...
    def outcome(self, state: StateT) -> OutcomeT | None: ...
    def legal_actions(self, state: StateT, seat_id: str) -> tuple[ActionT, ...]: ...
    def apply(
        self, state: StateT, seat_id: str, action: ActionT
    ) -> RuleTransition[StateT, ActionResultT, EventT]: ...
    def resign(self, state: StateT, seat_id: str) -> StateT: ...
