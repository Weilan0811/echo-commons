from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from echo_commons.shared.actors import ActorRef
from echo_commons.shared.message_sources import MessageSource, SystemSource


class MessageVisibility(StrEnum):
    CONVERSATION = "conversation"
    RECIPIENTS = "recipients"


@dataclass(frozen=True, slots=True)
class PlayerMessage:
    player_id: str
    client_message_id: str
    text: str
    mentions: tuple[ActorRef, ...] = ()
    reply_to_message_id: str | None = None

    def __post_init__(self) -> None:
        if not all(value.strip() for value in (self.player_id, self.client_message_id, self.text)):
            raise ValueError("Player identity, client message ID and text must be nonempty")
        if len(set(self.mentions)) != len(self.mentions):
            raise ValueError("Mentions must be unique")


@dataclass(frozen=True, slots=True)
class Message:
    message_id: str
    community_id: str
    conversation_id: str
    sequence: int
    sender: MessageSource
    sender_membership_id: str | None
    text: str
    visibility: MessageVisibility
    audience: tuple[str, ...]
    mentions: tuple[ActorRef, ...]
    reply_to_message_id: str | None
    client_message_id: str | None
    source_turn_id: str | None
    result_id: str | None
    trace_id: str
    created_at_utc: datetime
    activity_result_id: str | None = None

    def __post_init__(self) -> None:
        object.__setattr__(self, "visibility", MessageVisibility(self.visibility))
        if self.sequence < 1 or not self.text.strip():
            raise ValueError("Message requires a positive sequence and nonempty text")
        if isinstance(self.sender, SystemSource):
            if self.sender_membership_id is not None:
                raise ValueError("System message source cannot have a membership")
        elif self.sender_membership_id not in self.audience:
            raise ValueError("Sender membership must belong to the message audience")
