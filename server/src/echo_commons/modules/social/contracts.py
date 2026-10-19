import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Literal, Protocol

from echo_commons.modules.conversations.domain.conversation import Membership
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.social.domain import SocialTurn


@dataclass(frozen=True, slots=True)
class ResponseRequest:
    turn: SocialTurn
    member: Membership
    inputs: tuple[Message, ...]
    at: datetime


@dataclass(frozen=True, slots=True)
class ParticipationResult:
    turn_id: str
    character_id: str
    status: Literal["completed", "failed", "cancelled"]
    outcome: Literal["message", "silent", "failed", "cancelled"]
    message: Message | None = None


@dataclass(frozen=True, slots=True)
class TaskDispatchResult:
    task_id: str
    failure_code: str | None = None


class TaskCancellationPort(Protocol):
    def cancel_turn(
        self, connection: sqlite3.Connection, turn_id: str, reason: str, at: datetime
    ) -> None: ...


class ConversationTaskPort(TaskCancellationPort, Protocol):
    def reserve(
        self, connection: sqlite3.Connection, turn: SocialTurn, member: Membership, at: datetime
    ) -> str: ...

    def create(
        self,
        connection: sqlite3.Connection,
        request: ResponseRequest,
        *,
        task_id: str | None = None,
    ) -> TaskDispatchResult: ...


class SocialLifecyclePort(Protocol):
    def message_received(self, connection: sqlite3.Connection, message: Message) -> None: ...

    def task_finished(
        self, connection: sqlite3.Connection, result: ParticipationResult, at: datetime
    ) -> None: ...
