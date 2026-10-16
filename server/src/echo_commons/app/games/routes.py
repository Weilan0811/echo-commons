from typing import Annotated

from echo_games.public import (
    CancelGameCommand,
    GameStatus,
    GomokuActionReceipt,
    GomokuConfig,
    GomokuCreateGameCommand,
    GomokuDecisionInput,
    GomokuEvent,
    GomokuSubmitActionCommand,
    GomokuView,
    LeaveGameCommand,
    ResignGameCommand,
    StartGameCommand,
)
from fastapi import APIRouter, Depends, Query

from echo_commons.app.composition import Application
from echo_commons.app.games.access import GameRequester
from echo_commons.app.games.schemas import (
    CancelGameRequest,
    CreateGameRequest,
    EndGameRequest,
    GameOperationRequest,
    GameOperationResponse,
    GameSessionResponse,
    GameTypeResponse,
    GameTypesResponse,
    JoinGameRequest,
    LeaveGameRequest,
    ResignGameRequest,
    SubmitGameActionRequest,
)
from echo_commons.app.http import BUSINESS_RESPONSES, ErrorResponse, application_for
from echo_commons.modules.communities.contracts import (
    CreateGameSessionCommand,
    EndGameActivityCommand,
    JoinGameSessionCommand,
)
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.management import Page, PageOptions

router = APIRouter(
    prefix="/api",
    tags=["games"],
    responses={
        **BUSINESS_RESPONSES,
        403: {"model": ErrorResponse, "description": "没有执行该游戏操作的资格"},
    },
)
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.get("/game-types", response_model=GameTypesResponse)
def game_types(application: ApplicationDependency):
    return {"items": application.games.registry.list_game_types()}


@router.get("/game-types/{game_type}", response_model=GameTypeResponse)
def game_type(game_type: str, application: ApplicationDependency):
    return application.games.registry.read_game_type(game_type)


@router.get("/games", response_model=Page[GameSessionResponse])
def list_games(
    community_id: str,
    requester: GameRequester,
    application: ApplicationDependency,
    game_type: str | None = None,
    status: GameStatus | None = None,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    page = application.game_queries.list(
        requester,
        community_id,
        PageOptions(cursor=cursor, limit=limit),
        game_type=game_type,
        status=status,
    )
    return {**page, "items": [GameSessionResponse.from_session(item) for item in page["items"]]}


@router.post("/games", status_code=201, response_model=GameOperationResponse)
def create_game(body: CreateGameRequest, application: ApplicationDependency):
    result = application.game_participation.create_game(
        ActorRef("player", body.player_id),
        CreateGameSessionCommand[GomokuConfig](
            community_id=body.community_id,
            game=GomokuCreateGameCommand(**body.model_dump(exclude={"player_id", "community_id"})),
        ),
    )
    return GameOperationResponse.from_operation(result)


@router.get("/games/{game_id}", response_model=GameSessionResponse)
def read_game(game_id: str, requester: GameRequester, application: ApplicationDependency):
    return GameSessionResponse.from_session(application.game_queries.read(requester, game_id))


@router.post("/games/{game_id}/participants", response_model=GameOperationResponse)
def join_game(game_id: str, body: JoinGameRequest, application: ApplicationDependency):
    requester = ActorRef("player", body.player_id)
    result = application.game_participation.join_game(
        requester,
        JoinGameSessionCommand(
            game_id=game_id,
            participant=requester,
            **body.model_dump(exclude={"player_id"}),
        ),
    )
    return GameOperationResponse.from_operation(result)


@router.post("/games/{game_id}/leave", response_model=GameOperationResponse)
def leave_game(game_id: str, body: LeaveGameRequest, application: ApplicationDependency):
    result = application.game_participation.leave_game(
        ActorRef("player", body.player_id),
        LeaveGameCommand(game_id=game_id, **body.model_dump(exclude={"player_id"})),
    )
    return GameOperationResponse.from_operation(result)


@router.post("/games/{game_id}/start", response_model=GameOperationResponse)
def start_game(game_id: str, body: GameOperationRequest, application: ApplicationDependency):
    result = application.game_participation.start_game(
        ActorRef("player", body.player_id),
        StartGameCommand(game_id=game_id, **body.model_dump(exclude={"player_id"})),
    )
    return GameOperationResponse.from_operation(result)


@router.post("/games/{game_id}/resign", response_model=GameOperationResponse)
def resign_game(game_id: str, body: ResignGameRequest, application: ApplicationDependency):
    result = application.game_participation.resign_game(
        ActorRef("player", body.player_id),
        ResignGameCommand(game_id=game_id, **body.model_dump(exclude={"player_id"})),
    )
    return GameOperationResponse.from_operation(result)


@router.post("/games/{game_id}/cancel", response_model=GameOperationResponse)
def cancel_game(game_id: str, body: CancelGameRequest, application: ApplicationDependency):
    result = application.game_participation.cancel_game(
        ActorRef("player", body.player_id),
        CancelGameCommand(game_id=game_id, **body.model_dump(exclude={"player_id"})),
    )
    return GameOperationResponse.from_operation(result)


@router.post("/games/{game_id}/end", response_model=GameOperationResponse)
def end_game(game_id: str, body: EndGameRequest, application: ApplicationDependency):
    result = application.game_participation.end_activity(
        ActorRef("player", body.player_id),
        EndGameActivityCommand(game_id=game_id, **body.model_dump(exclude={"player_id"})),
    )
    return GameOperationResponse.from_operation(result)


@router.get("/games/{game_id}/operations/{request_id}", response_model=GameOperationResponse)
def read_operation(
    game_id: str, request_id: str, requester: GameRequester, application: ApplicationDependency
):
    result = application.game_participation.read_operation(requester, game_id, request_id)
    if result is None:
        raise NotFoundError("Game operation receipt does not exist for this requester")
    return GameOperationResponse.from_operation(result)


@router.get("/games/{game_id}/view", response_model=GomokuView)
def read_view(game_id: str, requester: GameRequester, application: ApplicationDependency):
    return application.game_queries.view(requester, game_id)


@router.get("/games/{game_id}/decision-input", response_model=GomokuDecisionInput)
def read_decision_input(
    game_id: str, opportunity_id: str, requester: GameRequester, application: ApplicationDependency
):
    return application.game_queries.decision_input(requester, game_id, opportunity_id)


@router.post("/games/{game_id}/actions", response_model=GomokuActionReceipt)
def submit_action(game_id: str, body: SubmitGameActionRequest, application: ApplicationDependency):
    return application.game_participation.submit_action(
        ActorRef("player", body.player_id),
        game_id,
        GomokuSubmitActionCommand(**body.model_dump(exclude={"player_id"})),
    )


@router.get("/games/{game_id}/actions/{request_id}", response_model=GomokuActionReceipt)
def read_receipt(
    game_id: str,
    request_id: str,
    requester: GameRequester,
    application: ApplicationDependency,
    participation_id: str | None = None,
):
    return application.game_queries.receipt(requester, game_id, request_id, participation_id)


@router.get("/games/{game_id}/events", response_model=Page[GomokuEvent])
def read_events(
    game_id: str,
    requester: GameRequester,
    application: ApplicationDependency,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
    participation_id: str | None = None,
    through_state_version: int | None = Query(default=None, ge=1),
):
    return application.game_queries.events(
        requester,
        game_id,
        PageOptions(cursor=cursor, limit=limit),
        participation_id=participation_id,
        through_state_version=through_state_version,
    )
