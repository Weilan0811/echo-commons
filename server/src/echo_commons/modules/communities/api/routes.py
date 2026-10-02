from typing import Annotated

from fastapi import APIRouter, Depends

from echo_commons.app.composition import Application
from echo_commons.app.http import application_for
from echo_commons.modules.communities.api.schemas import (
    CommunityView,
    CreateCommunity,
    PlayerView,
    RegisterPlayer,
)
from echo_commons.shared.actors import ActorRef

router = APIRouter(prefix="/api", tags=["communities"])
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.post("/communities", status_code=201, response_model=CommunityView)
def create_community(body: CreateCommunity, application: ApplicationDependency):
    community = application.communities.create(
        body.name, body.timezone, community_id=body.community_id, world_time=body.world_time_utc
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
