from typing import Annotated

from fastapi import APIRouter, Depends

from echo_commons.app.composition import Application
from echo_commons.app.http import BUSINESS_RESPONSES, application_for
from echo_commons.modules.characters.api.schemas import (
    BlueprintView,
    CharacterView,
    CreateCharacter,
)

router = APIRouter(prefix="/api", tags=["characters"], responses=BUSINESS_RESPONSES)
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.get("/blueprints", response_model=list[BlueprintView])
def list_blueprints(application: ApplicationDependency):
    return [
        BlueprintView(
            blueprint_id=blueprint_id,
            display_name=blueprint.display_name,
            content_version=blueprint.content_version,
            status=blueprint.status,
            avatar_url=blueprint.avatar_url,
        )
        for blueprint_id, blueprint in application.catalog.blueprints.items()
    ]


@router.post(
    "/communities/{community_id}/characters", status_code=201, response_model=CharacterView
)
def create_character(community_id: str, body: CreateCharacter, application: ApplicationDependency):
    instance = application.characters.create(
        community_id, body.blueprint_id, character_id=body.character_id, player_id=body.player_id
    )
    return application.community_query.character_view(instance)


@router.get("/communities/{community_id}/characters", response_model=list[CharacterView])
def list_characters(community_id: str, player_id: str, application: ApplicationDependency):
    return application.community_query.characters(community_id, player_id)
