from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Generic, Literal, Protocol, TypeVar

from echo_games.public import CreateGameCommand, GameOperationReceipt
from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from echo_commons.modules.communities.domain import Community, CommunityStatus, Player
from echo_commons.modules.conversations.domain.conversation import Conversation, Membership
from echo_commons.shared.actors import ActorRef

ConfigT = TypeVar("ConfigT", bound=BaseModel)
GameSessionOperationKind = Literal["create", "join", "leave", "start", "resign", "cancel", "end"]


class CommunityReader(Protocol):
    def get(self, connection: sqlite3.Connection, community_id: str) -> Community: ...
    def require_member(
        self, connection: sqlite3.Connection, community_id: str, actor: ActorRef
    ) -> None: ...

    def player(self, connection: sqlite3.Connection, player_id: str) -> Player: ...


class CommunityLifecycle(Protocol):
    def community_changed(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        status: CommunityStatus,
        now: datetime,
    ) -> None: ...


class GameSessionCommand(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)


class CreateGameSessionCommand(GameSessionCommand, Generic[ConfigT]):
    community_id: str = Field(min_length=1, pattern=r"\S")
    game: SerializeAsAny[CreateGameCommand[ConfigT]]


class JoinGameSessionCommand(GameSessionCommand):
    game_id: str = Field(min_length=1, pattern=r"\S")
    request_id: str = Field(min_length=1, pattern=r"\S")
    expected_state_version: int = Field(ge=1)
    seat_id: str = Field(min_length=1, pattern=r"\S")
    participant: ActorRef


class EndGameActivityCommand(GameSessionCommand):
    game_id: str = Field(min_length=1, pattern=r"\S")
    request_id: str = Field(min_length=1, pattern=r"\S")
    expected_state_version: int = Field(ge=1)
    expected_conversation_version: int = Field(ge=1)


@dataclass(frozen=True)
class GameSessionOperationResult:
    community_id: str
    game_id: str
    operation: GameSessionOperationKind
    conversation: Conversation
    memberships: tuple[Membership, ...]
    game_receipt: SerializeAsAny[GameOperationReceipt] | None


class GameSessionOperationSnapshot(GameSessionCommand):
    conversation: Conversation
    memberships: tuple[Membership, ...]
    game_request_id: str | None
