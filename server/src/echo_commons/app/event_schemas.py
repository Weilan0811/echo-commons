from typing import Literal

from pydantic import BaseModel, ConfigDict, Field
from pydantic.json_schema import models_json_schema

from echo_commons.modules.conversations.api.schemas import PlayerMessageView
from echo_commons.shared.realtime import EventKind


class CommunityEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    community_id: str


class ConversationEventData(CommunityEventData):
    conversation_id: str


class CharacterEventData(CommunityEventData):
    character_id: str


class GameChangedData(CommunityEventData):
    game_id: str
    state_version: int = Field(ge=1)


class MessageEventData(ConversationEventData):
    message: PlayerMessageView


class CursorResponse(BaseModel):
    cursor: str


class CheckpointData(BaseModel):
    model_config = ConfigDict(extra="forbid")


class ResyncData(CheckpointData):
    reason: Literal["cursor_expired"]


class AccessRevokedData(CheckpointData):
    reason: Literal["membership_required"]


EVENT_DATA_MODELS = {
    kind: GameChangedData
    if kind is EventKind.GAME
    else MessageEventData
    if kind is EventKind.MESSAGE
    else CharacterEventData
    if kind is EventKind.CHARACTER_APPEARANCE
    else CommunityEventData
    if kind in (EventKind.COMMUNITY, EventKind.COMMUNITY_APPEARANCE)
    else ConversationEventData
    for kind in EventKind
}

CONTROL_DATA_MODELS = {
    "checkpoint": CheckpointData,
    "resync_required": ResyncData,
    "access_revoked": AccessRevokedData,
}


def include_event_schemas(document: dict) -> dict:
    models = {**EVENT_DATA_MODELS, **CONTROL_DATA_MODELS}
    references, definitions = models_json_schema(
        [(model, "serialization") for model in dict.fromkeys(models.values())],
        ref_template="#/components/schemas/{model}",
    )
    schemas = document.setdefault("components", {}).setdefault("schemas", {})
    for name, definition in definitions.get("$defs", {}).items():
        schemas.setdefault(name, definition)
    schemas["EventPayloadMap"] = {
        "type": "object",
        "title": "EventPayloadMap",
        "properties": {
            kind: references[(model, "serialization")] for kind, model in models.items()
        },
        "required": list(models),
        "additionalProperties": False,
    }
    return document
