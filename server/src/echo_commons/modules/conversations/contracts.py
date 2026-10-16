from __future__ import annotations

import sqlite3
from datetime import datetime
from typing import Protocol

from echo_commons.modules.conversations.domain.conversation import Conversation, Membership
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.shared.actors import ActorRef


class ConversationReader(Protocol):
    def current(
        self, connection: sqlite3.Connection, conversation_id: str, actor: ActorRef
    ) -> Membership: ...

    def for_actor(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        actor: ActorRef,
    ) -> tuple[Conversation, ...]: ...
    def get(
        self, connection: sqlite3.Connection, community_id: str, conversation_id: str
    ) -> Conversation: ...
    def members(
        self, connection: sqlite3.Connection, conversation_id: str, *, current_only: bool = True
    ) -> tuple[Membership, ...]: ...


class MessageReader(Protocol):
    def get(
        self, connection: sqlite3.Connection, conversation_id: str, message_id: str
    ) -> Message: ...
    def scan(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        after: int,
        upper: int,
        limit: int,
    ) -> tuple[Message, ...]: ...


class ConversationLifecycle(Protocol):
    def member_left(
        self, connection: sqlite3.Connection, membership_id: str, now: datetime
    ) -> None: ...
    def archived(
        self, connection: sqlite3.Connection, conversation_id: str, now: datetime
    ) -> None: ...


class GameConversationAccess(Protocol):
    def can_send(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        conversation_id: str,
        actor: ActorRef,
    ) -> bool: ...
