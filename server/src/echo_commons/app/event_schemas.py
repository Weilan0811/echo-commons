from typing import Literal

from pydantic import BaseModel, ConfigDict

from echo_commons.modules.conversations.api.schemas import PlayerMessageView
from echo_commons.shared.realtime import EventKind


class CommunityEventData(BaseModel):
    model_config = ConfigDict(extra="forbid")
    community_id: str


class ConversationEventData(CommunityEventData):
    conversation_id: str


class CharacterEventData(CommunityEventData):
    character_id: str


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
    kind: MessageEventData
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
