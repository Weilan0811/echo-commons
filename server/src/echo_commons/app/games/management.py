from typing import Annotated

from echo_games.public import GameInspectionPayload, GameInspectionRecord, Participation
from fastapi import APIRouter, Depends

from echo_commons.app.composition import Application
from echo_commons.app.http import ErrorResponse, application_for
from echo_commons.app.management import Pagination
from echo_commons.modules.communities.game_management import GameRecordKind
from echo_commons.shared.management import ManagementModel, Page


class GameInspectionResponse(ManagementModel):
    game: GameInspectionPayload
    participations: list[Participation]


router = APIRouter(
    prefix="/internal/communities/{community_id}/conversations/{conversation_id}/game",
    tags=["management"],
    responses={
        400: {"model": ErrorResponse, "description": "业务输入或游标无效"},
        404: {"model": ErrorResponse, "description": "对象不存在或不属于请求范围"},
        500: {"model": ErrorResponse, "description": "响应或存储不可用"},
        503: {"model": ErrorResponse, "description": "存储暂时不可用"},
    },
)
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.get("", response_model=GameInspectionResponse)
def inspection(community_id: str, conversation_id: str, application: ApplicationDependency):
    return application.game_management.inspection(community_id, conversation_id)


@router.get("/records", response_model=Page[GameInspectionRecord])
def records(
    community_id: str,
    conversation_id: str,
    kind: GameRecordKind,
    application: ApplicationDependency,
    page: Pagination,
):
    return application.game_management.records(community_id, conversation_id, kind, page)
