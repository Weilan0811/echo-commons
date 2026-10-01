"""Public camelCase API DTOs; these are intentionally separate from domain types."""

from __future__ import annotations

from datetime import datetime
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, field_validator


class ApiModel(BaseModel):
    model_config = ConfigDict(extra="forbid", populate_by_name=True)


class SendMessageRequest(ApiModel):
    conversation_id: str = Field(alias="conversationId", min_length=1)
    player_text: str = Field(alias="playerText", min_length=1)
    images: list[str] = Field(default_factory=list)
    client_msg_id: UUID = Field(alias="clientMsgId")
    local_timestamp: datetime | None = Field(default=None, alias="localTimestamp")

    @field_validator("local_timestamp")
    @classmethod
    def timestamp_must_be_aware(cls, value: datetime | None) -> datetime | None:
        if value is not None and value.tzinfo is None:
            raise ValueError("localTimestamp must include a timezone")
        return value

    @field_validator("player_text")
    @classmethod
    def player_text_must_not_be_blank(cls, value: str) -> str:
        if not value.strip():
            raise ValueError("playerText must not be blank")
        return value


class SendMessageResponse(ApiModel):
    accepted: bool
    message_id: UUID = Field(alias="messageId")
    client_msg_id: UUID = Field(alias="clientMsgId")
    trace_id: UUID = Field(alias="traceId")


class MessageSenderResponse(ApiModel):
    type: str
    id: str


class MessageResponse(ApiModel):
    message_id: UUID = Field(alias="messageId")
    client_msg_id: UUID | None = Field(default=None, alias="clientMsgId")
    conversation_id: str = Field(alias="conversationId")
    sender: MessageSenderResponse
    text: str
    images: list[str]
    reply_to_message_id: UUID | None = Field(default=None, alias="replyToMessageId")
    server_timestamp: datetime = Field(alias="serverTimestamp")


class ChipsResponse(ApiModel):
    status_hint: str | None = Field(default=None, alias="statusHint")
    suggestions: list[str] = Field(default_factory=list)


class TraceResponse(ApiModel):
    trace_id: UUID = Field(alias="traceId")
    kind: str
    entity_type: str = Field(alias="entityType")
    entity_id: str = Field(alias="entityId")


class SyncMessagesResponse(ApiModel):
    messages: list[MessageResponse]
    next_cursor: str = Field(alias="nextCursor")
    chips: ChipsResponse
    traces: list[TraceResponse]


class ErrorResponse(ApiModel):
    code: str
    message: str
    trace_id: UUID = Field(alias="traceId")


class PublicTrace(ApiModel):
    """Marker DTO kept separate to avoid accidentally exposing internal payloads."""

    model_config = ConfigDict(extra="forbid")
