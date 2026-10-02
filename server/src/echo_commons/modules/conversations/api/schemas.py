from datetime import datetime

from pydantic import BaseModel, Field

from echo_commons.app.http import RequestModel
from echo_commons.modules.conversations.domain.conversation import (
    ConversationKind,
    ConversationStatus,
)
from echo_commons.modules.conversations.domain.message import MessageVisibility
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.message_sources import MessageSource


class CreateConversation(RequestModel):
    kind: ConversationKind
    actors: tuple[ActorRef, ...]
    conversation_id: str | None = Field(default=None, min_length=1)


class SendMessage(RequestModel):
    player_id: str = Field(min_length=1)
    client_message_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    visibility: MessageVisibility = MessageVisibility.CONVERSATION
    recipients: tuple[ActorRef, ...] = ()
    mentions: tuple[ActorRef, ...] = ()
    reply_to_message_id: str | None = Field(default=None, min_length=1)


class ConversationView(BaseModel):
    conversation_id: str
    community_id: str
    kind: ConversationKind
    status: ConversationStatus
    membership_version: int
    created_at_utc: datetime


class MembershipView(BaseModel):
    membership_id: str
    community_id: str
    conversation_id: str
    actor: ActorRef
    joined_at_utc: datetime
    left_at_utc: datetime | None


class MessageView(BaseModel):
    message_id: str
    conversation_id: str
    sequence: int
    sender: MessageSource
    text: str
    visibility: MessageVisibility
    mentions: tuple[ActorRef, ...]
    reply_to_message_id: str | None
    source_turn_id: str | None
    created_at_utc: datetime


class MessageReceipt(BaseModel):
    message_id: str
    conversation_id: str
    sequence: int
    trace_id: str


class MessagePageView(BaseModel):
    messages: tuple[MessageView, ...]
    cursor: str
    has_more: bool
