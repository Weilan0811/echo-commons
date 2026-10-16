from datetime import datetime
from typing import Literal

from pydantic import BaseModel, Field

from echo_commons.app.http import RequestModel
from echo_commons.modules.conversations.domain.conversation import (
    ConversationKind,
    ConversationStatus,
)
from echo_commons.modules.conversations.domain.message import MessageVisibility
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.message_sources import MessageSource
from echo_commons.shared.public import PublicDisplay


class CreateConversation(RequestModel):
    player_id: str = Field(min_length=1)
    kind: Literal[ConversationKind.DIRECT, ConversationKind.GROUP]
    actors: tuple[ActorRef, ...]
    conversation_id: str | None = Field(default=None, min_length=1)


class SendMessage(RequestModel):
    player_id: str = Field(min_length=1)
    client_message_id: str = Field(min_length=1)
    text: str = Field(min_length=1)
    mentions: tuple[ActorRef, ...] = ()
    reply_to_message_id: str | None = Field(default=None, min_length=1)


class ConversationView(BaseModel):
    conversation_id: str
    community_id: str
    kind: ConversationKind
    status: ConversationStatus
    membership_version: int
    created_at_utc: datetime
    state_version: int
    creator_player_id: str | None
    legacy_small_group: bool


class ArchiveConversation(RequestModel):
    player_id: str = Field(min_length=1)
    client_operation_id: str = Field(min_length=1)
    expected_state_version: int = Field(ge=1)


class ConversationListPreference(RequestModel):
    player_id: str = Field(min_length=1)
    client_operation_id: str = Field(min_length=1)
    hidden: bool


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


class MessagePreview(BaseModel):
    message_id: str
    sequence: int
    sender_display: PublicDisplay
    text_preview: str
    visibility: MessageVisibility
    created_at_utc: datetime


class PlayerMessageView(MessageView):
    sender_display: PublicDisplay
    recipients: tuple[PublicDisplay, ...]
    reply_preview: MessagePreview | None


class PlayerConversationSummary(ConversationView):
    creator_display: PublicDisplay | None
    hidden: bool
    can_archive: bool
    can_join: bool
    can_leave: bool
    display_name: str
    self_membership_status: Literal["current", "past"]
    self_membership_id: str | None
    can_send: bool
    direct_peer: PublicDisplay | None
    last_message: MessagePreview | None
    last_visible_message_at_utc: datetime | None
    last_read_sequence: int
    unread_count: int


class ReadMarker(RequestModel):
    player_id: str = Field(min_length=1)
    through_message_id: str = Field(min_length=1)


class ReadState(BaseModel):
    conversation_id: str
    last_read_sequence: int
    unread_count: int


class JoinMembership(RequestModel):
    player_id: str = Field(min_length=1)
    client_operation_id: str = Field(min_length=1)


class ManageMembership(RequestModel):
    client_operation_id: str = Field(min_length=1)
    expected_membership_version: int = Field(ge=0)


class MessageHistoryView(BaseModel):
    messages: tuple[PlayerMessageView, ...]
    older_cursor: str | None
    has_older: bool
    poll_cursor: str | None


class MessagePageView(BaseModel):
    messages: tuple[PlayerMessageView, ...]
    cursor: str
    has_more: bool
