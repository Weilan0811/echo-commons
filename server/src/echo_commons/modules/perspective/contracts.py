from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from pydantic import BaseModel, ConfigDict, Field

from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.perspective.activities import ActivityPerspective
from echo_commons.shared.actors import ActorRef


class ConversationBoundary(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    conversation_id: str
    kind: str
    name: str
    upper_sequence: int = Field(ge=0)
    membership_ids: tuple[str, ...]


class ActivityObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    observation_id: str = Field(min_length=1)
    community_id: str = Field(min_length=1)
    activity_id: str = Field(min_length=1)
    observer: ActorRef
    occurred_at_utc: datetime
    state_version: int = Field(ge=1)
    audience: tuple[ActorRef, ...] = Field(min_length=1)
    content: str = Field(min_length=1)


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
    activities: ActivityPerspective | None

    def observe(self, connection: sqlite3.Connection, scope: ObservationScope) -> Observation: ...

    def freeze(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        actor: ActorRef,
        observed_at: datetime,
        *,
        conversation_id: str | None = None,
        upper_sequence: int | None = None,
    ) -> tuple[ConversationBoundary, ...]: ...

    def experiences(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        actor: ActorRef,
        boundaries: tuple[ConversationBoundary, ...],
        observed_at: datetime,
    ) -> tuple[Message, ...]: ...
