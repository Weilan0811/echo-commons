from typing import Annotated

from fastapi import APIRouter, Depends

from echo_commons.app.composition import Application
from echo_commons.app.http import BUSINESS_RESPONSES, application_for
from echo_commons.modules.characters.api.schemas import (
    BlueprintView,
    CharacterView,
    CreateCharacter,
    RetryMemory,
    UpdateCharacterAppearance,
)
from echo_commons.modules.characters.services.appearance import update_avatar

router = APIRouter(prefix="/api", tags=["characters"], responses=BUSINESS_RESPONSES)
ApplicationDependency = Annotated[Application, Depends(application_for)]


@router.patch(
    "/communities/{community_id}/characters/{character_id}/appearance", response_model=CharacterView
)
def appearance(
    community_id: str,
    character_id: str,
    body: UpdateCharacterAppearance,
    application: ApplicationDependency,
):
    update_avatar(application.database, community_id, character_id, body)
    with application.database.read() as connection:
        instance = application.community_query.identity.instances.get(
            connection, community_id, character_id
        )
    return application.community_query.character_view(instance)


@router.get("/blueprints", response_model=list[BlueprintView])
def list_blueprints(application: ApplicationDependency):
    return [
        BlueprintView(
            blueprint_id=blueprint_id,
            display_name=blueprint.display_name,
            content_version=blueprint.content_version,
            status=blueprint.status,
            avatar_url=blueprint.avatar_url,
            illustration_url=blueprint.illustration_url,
        )
        for blueprint_id, blueprint in application.catalog.blueprints.items()
    ]


@router.post(
    "/communities/{community_id}/characters", status_code=201, response_model=CharacterView
)
def create_character(community_id: str, body: CreateCharacter, application: ApplicationDependency):
    instance = application.characters.create(
        community_id,
        body.blueprint_id,
        character_id=body.character_id,
        player_id=body.player_id,
        memory_mode=body.memory_mode,
        person_id=body.person_id,
    )
    return application.community_query.character_view(instance)


@router.get("/communities/{community_id}/characters", response_model=list[CharacterView])
def list_characters(community_id: str, player_id: str, application: ApplicationDependency):
    return application.community_query.characters(community_id, player_id)


@router.post(
    "/communities/{community_id}/characters/{character_id}/memory/retry",
    response_model=CharacterView,
)
def retry_memory(
    community_id: str, character_id: str, body: RetryMemory, application: ApplicationDependency
):
    instance = application.characters.retry_memory(
        community_id, character_id, player_id=body.player_id
    )
    return application.community_query.character_view(instance)
