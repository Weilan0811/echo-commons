from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from typing import Protocol

from echo_commons.modules.conversations.domain.message import Message
from echo_commons.shared.actors import ActorRef


class ActorNames(Protocol):
    def actor_name(
        self, connection: sqlite3.Connection, community_id: str, actor: ActorRef
    ) -> str: ...


@dataclass(frozen=True, slots=True)
class ObservationScope:
    community_id: str
    conversation_id: str
    actor: ActorRef
    upper_sequence: int
    membership_id: str | None = None

    def __post_init__(self) -> None:
        if self.upper_sequence < 0:
            raise ValueError("Observation sequence must be nonnegative")


class PerspectiveReader(Protocol):
    def visible(
        self, connection: sqlite3.Connection, scope: ObservationScope, message: Message
    ) -> bool: ...
    def messages(
        self, connection: sqlite3.Connection, scope: ObservationScope, *, after: int = 0
    ) -> tuple[Message, ...]: ...


@dataclass(frozen=True, slots=True)
class PublicParticipant:
    actor: ActorRef
    display_name: str
    membership_id: str


@dataclass(frozen=True, slots=True)
class Observation:
    messages: tuple[Message, ...]
    participants: tuple[PublicParticipant, ...]


class WorldReader(ActorNames, Protocol):
    def observe(self, connection: sqlite3.Connection, scope: ObservationScope) -> Observation: ...
