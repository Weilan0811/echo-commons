from typing import Annotated, Literal

from fastapi import APIRouter, Depends, Query

from echo_commons.app.composition import Application
from echo_commons.app.http import BUSINESS_RESPONSES, application_for
from echo_commons.modules.communities.api.schemas import (
    CommunityCard,
    CommunityView,
    CreateCommunity,
    PlayerView,
    RegisterPlayer,
)
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.management import Page, PageOptions
from echo_commons.shared.public import PublicDisplay

router = APIRouter(prefix="/api", tags=["communities"], responses=BUSINESS_RESPONSES)
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.post("/communities", status_code=201, response_model=CommunityView)
def create_community(body: CreateCommunity, application: ApplicationDependency):
    community = application.communities.create(
        body.name,
        body.timezone,
        community_id=body.community_id,
        world_time=body.world_time_utc,
        player_id=body.player_id,
    )
    return CommunityView.model_validate(community, from_attributes=True)


@router.post("/players", status_code=201, response_model=PlayerView)
def register_player(body: RegisterPlayer, application: ApplicationDependency):
    player = application.communities.register_player(body.display_name, player_id=body.player_id)
    return PlayerView.model_validate(player, from_attributes=True)


@router.put("/communities/{community_id}/players/{player_id}")
def join_player(community_id: str, player_id: str, application: ApplicationDependency):
    application.communities.join(community_id, ActorRef("player", player_id))
    return {"community_id": community_id, "player_id": player_id}


@router.get("/players", response_model=Page[PlayerView])
def players(
    application: ApplicationDependency,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return application.community_query.players(PageOptions(cursor=cursor, limit=limit))


@router.get("/players/{player_id}", response_model=PlayerView)
def player(player_id: str, application: ApplicationDependency):
    return PlayerView.model_validate(
        application.community_query.player(player_id), from_attributes=True
    )


@router.get("/communities", response_model=Page[CommunityCard])
def communities(
    player_id: str,
    application: ApplicationDependency,
    scope: Literal["joined", "available"] = "joined",
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return application.community_query.communities(
        player_id, scope, PageOptions(cursor=cursor, limit=limit)
    )


@router.get("/communities/{community_id}", response_model=CommunityView)
def community(community_id: str, player_id: str, application: ApplicationDependency):
    return CommunityView.model_validate(
        application.community_query.community(community_id, player_id), from_attributes=True
    )


@router.get("/communities/{community_id}/members", response_model=Page[PublicDisplay])
def members(
    community_id: str,
    player_id: str,
    application: ApplicationDependency,
    cursor: str | None = None,
    limit: int = Query(default=50, ge=1, le=200),
):
    return application.community_query.members(
        community_id, player_id, PageOptions(cursor=cursor, limit=limit)
    )
