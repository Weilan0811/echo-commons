import sqlite3
from dataclasses import dataclass
from enum import StrEnum
from typing import Protocol, cast


class EventKind(StrEnum):
    MESSAGE = "conversation.message_created"
    TURNS = "conversation.turns_changed"
    SUMMARY = "conversation.summary_changed"
    MEMBERS = "conversation.members_changed"
    READ = "conversation.read_changed"
    COMMUNITY = "community.status_changed"
    COMMUNITY_APPEARANCE = "community.appearance_changed"
    CHARACTER_APPEARANCE = "character.appearance_changed"


class EventSource(StrEnum):
    MESSAGE = "message"
    TURN = "turn"
    CONVERSATION = "conversation"
    READ = "read"
    COMMUNITY = "community"
    CHARACTER = "character"


@dataclass(frozen=True, slots=True)
class EventReference:
    kind: EventKind
    community_id: str
    object_id: str
    source: EventSource
    source_id: str
    audience: tuple[str, ...] = ()


class EventTransaction(Protocol):
    def record_event(self, event: EventReference) -> None: ...


def record_event(connection: sqlite3.Connection, event: EventReference) -> None:
    cast(EventTransaction, connection).record_event(event)
