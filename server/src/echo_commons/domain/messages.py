from __future__ import annotations

from dataclasses import dataclass, field
from datetime import datetime
from enum import StrEnum
from typing import Any
from uuid import UUID

from echo_commons.domain.errors import DomainInvariantError, require_non_empty, require_sequence


class SenderType(StrEnum):
    PLAYER = "player"
    CHARACTER = "character"
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class MessageSender:
    type: SenderType
    id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "type", SenderType(self.type))
        object.__setattr__(self, "id", require_non_empty(self.id, "sender.id"))


@dataclass(frozen=True, slots=True)
class Message:
    message_sequence: int
    message_id: UUID
    account_id: str
    conversation_id: str
    sender: MessageSender
    text: str
    images: tuple[str, ...]
    client_msg_id: UUID | None
    client_timestamp_utc: datetime | None
    server_timestamp_utc: datetime
    reply_to_message_id: UUID | None
    trace_id: UUID
    input_batch_id: UUID | None = None
    result_id: UUID | None = None
    bubble_index: int | None = None

    def __post_init__(self) -> None:
        """Validate canonical Runtime links."""

        if self.input_batch_id is not None and not isinstance(self.input_batch_id, UUID):
            raise DomainInvariantError("input_batch_id must be a UUID or None")
        if self.result_id is not None and not isinstance(self.result_id, UUID):
            raise DomainInvariantError("result_id must be a UUID or None")
        if self.input_batch_id is not None and self.sender.type is not SenderType.PLAYER:
            raise DomainInvariantError("input_batch_id is valid only for player messages")
        if self.result_id is not None and self.sender.type is not SenderType.CHARACTER:
            raise DomainInvariantError("result_id is valid only for character messages")
        if self.bubble_index is not None:
            if self.sender.type is not SenderType.CHARACTER or self.result_id is None:
                raise DomainInvariantError("bubble_index requires a character result link")
            require_sequence(self.bubble_index, "bubble_index", minimum=0)

    @classmethod
    def player(
        cls,
        *,
        message_sequence: int,
        message_id: UUID,
        account_id: str,
        conversation_id: str,
        sender_id: str,
        text: str,
        images: tuple[str, ...],
        client_msg_id: UUID,
        client_timestamp_utc: datetime | None,
        server_timestamp_utc: datetime,
        input_batch_id: UUID,
        reply_to_message_id: UUID | None,
        trace_id: UUID,
    ) -> Message:
        return cls(
            message_sequence=message_sequence,
            message_id=message_id,
            account_id=account_id,
            conversation_id=conversation_id,
            sender=MessageSender(type=SenderType.PLAYER, id=sender_id),
            text=text,
            images=images,
            client_msg_id=client_msg_id,
            client_timestamp_utc=client_timestamp_utc,
            server_timestamp_utc=server_timestamp_utc,
            reply_to_message_id=reply_to_message_id,
            trace_id=trace_id,
            input_batch_id=input_batch_id,
        )

    @classmethod
    def character(
        cls,
        *,
        message_sequence: int,
        message_id: UUID,
        account_id: str,
        conversation_id: str,
        character_id: str,
        text: str,
        server_timestamp_utc: datetime,
        result_id: UUID,
        bubble_index: int,
        reply_to_message_id: UUID | None,
        trace_id: UUID,
        images: tuple[str, ...] = (),
    ) -> Message:
        return cls(
            message_sequence=message_sequence,
            message_id=message_id,
            account_id=account_id,
            conversation_id=conversation_id,
            sender=MessageSender(type=SenderType.CHARACTER, id=character_id),
            text=text,
            images=images,
            client_msg_id=None,
            client_timestamp_utc=None,
            server_timestamp_utc=server_timestamp_utc,
            reply_to_message_id=reply_to_message_id,
            trace_id=trace_id,
            result_id=result_id,
            bubble_index=bubble_index,
        )

    @classmethod
    def system(
        cls,
        *,
        message_sequence: int,
        message_id: UUID,
        account_id: str,
        conversation_id: str,
        text: str,
        server_timestamp_utc: datetime,
        trace_id: UUID,
        system_id: str = "system",
        images: tuple[str, ...] = (),
    ) -> Message:
        return cls(
            message_sequence=message_sequence,
            message_id=message_id,
            account_id=account_id,
            conversation_id=conversation_id,
            sender=MessageSender(type=SenderType.SYSTEM, id=system_id),
            text=text,
            images=images,
            client_msg_id=None,
            client_timestamp_utc=None,
            server_timestamp_utc=server_timestamp_utc,
            reply_to_message_id=None,
            trace_id=trace_id,
        )


@dataclass(frozen=True, slots=True)
class SubmitMessageCommand:
    account_id: str
    conversation_id: str
    player_text: str
    images: tuple[str, ...]
    client_msg_id: UUID
    local_timestamp: datetime | None
    trace_id: UUID | None = None


@dataclass(frozen=True, slots=True)
class MessageReceipt:
    accepted: bool
    message_id: UUID
    client_msg_id: UUID
    trace_id: UUID


@dataclass(frozen=True, slots=True)
class SyncMessagesQuery:
    account_id: str
    since: str | None = None
    limit: int = 100


@dataclass(frozen=True, slots=True)
class ConversationSyncQuery:
    """A message sync query scoped to one durable conversation."""

    account_id: str
    conversation_id: str
    since: str | None = None
    limit: int = 100


@dataclass(frozen=True, slots=True)
class ClientTrace:
    trace_id: UUID
    kind: str
    entity_type: str
    entity_id: str


@dataclass(frozen=True, slots=True)
class MessageBatch:
    messages: tuple[Message, ...]
    next_cursor: str
    chips: dict[str, Any] = field(default_factory=lambda: {"status_hint": None, "suggestions": []})
    traces: tuple[ClientTrace, ...] = ()
