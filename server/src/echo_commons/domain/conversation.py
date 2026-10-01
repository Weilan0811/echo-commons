from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from echo_commons.domain.errors import (
    DomainInvariantError,
    optional_utc,
    require_non_empty,
    require_utc,
)


class ConversationKind(StrEnum):
    DIRECT = "direct"
    GROUP = "group"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


@dataclass(frozen=True, slots=True)
class Conversation:
    """The durable identity and execution capability of one chat."""

    conversation_id: str
    account_id: str
    kind: ConversationKind | str
    created_at_utc: datetime
    updated_at_utc: datetime
    status: ConversationStatus | str = ConversationStatus.ACTIVE
    context_version: str = "0"

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "conversation_id", require_non_empty(self.conversation_id, "conversation_id")
        )
        object.__setattr__(self, "account_id", require_non_empty(self.account_id, "account_id"))
        object.__setattr__(self, "kind", ConversationKind(self.kind))
        object.__setattr__(self, "status", ConversationStatus(self.status))
        object.__setattr__(
            self, "context_version", require_non_empty(self.context_version, "context_version")
        )
        created = require_utc(self.created_at_utc, "created_at_utc")
        updated = require_utc(self.updated_at_utc, "updated_at_utc")
        if updated < created:
            raise DomainInvariantError("updated_at_utc must not be earlier than created_at_utc")
        object.__setattr__(self, "created_at_utc", created)
        object.__setattr__(self, "updated_at_utc", updated)

    @property
    def can_execute_agent(self) -> bool:
        """Whether S2.5 may create a character task for this conversation."""

        return self.status is ConversationStatus.ACTIVE and self.kind is ConversationKind.DIRECT

    def archive(self, *, now_utc: datetime) -> Conversation:
        now = require_utc(now_utc, "now_utc")
        if self.status is ConversationStatus.ARCHIVED:
            raise DomainInvariantError("an archived conversation cannot be archived again")
        if now < self.updated_at_utc:
            raise DomainInvariantError("conversation time cannot move backwards")
        return Conversation(
            conversation_id=self.conversation_id,
            account_id=self.account_id,
            kind=self.kind,
            created_at_utc=self.created_at_utc,
            updated_at_utc=now,
            status=ConversationStatus.ARCHIVED,
            context_version=self.context_version,
        )

    def with_context_version(self, context_version: str, *, now_utc: datetime) -> Conversation:
        version = require_non_empty(context_version, "context_version")
        now = require_utc(now_utc, "now_utc")
        if now < self.updated_at_utc:
            raise DomainInvariantError("conversation time cannot move backwards")
        return Conversation(
            conversation_id=self.conversation_id,
            account_id=self.account_id,
            kind=self.kind,
            created_at_utc=self.created_at_utc,
            updated_at_utc=now,
            status=self.status,
            context_version=version,
        )


@dataclass(frozen=True, slots=True)
class ConversationParticipant:
    """A character's membership interval in a conversation."""

    conversation_id: str
    character_id: str
    joined_at_utc: datetime
    left_at_utc: datetime | None = None

    def __post_init__(self) -> None:
        object.__setattr__(
            self, "conversation_id", require_non_empty(self.conversation_id, "conversation_id")
        )
        object.__setattr__(
            self, "character_id", require_non_empty(self.character_id, "character_id")
        )
        joined = require_utc(self.joined_at_utc, "joined_at_utc")
        left = optional_utc(self.left_at_utc, "left_at_utc")
        if left is not None and left < joined:
            raise DomainInvariantError("left_at_utc must not be earlier than joined_at_utc")
        object.__setattr__(self, "joined_at_utc", joined)
        object.__setattr__(self, "left_at_utc", left)

    @property
    def is_active(self) -> bool:
        return self.left_at_utc is None

    def leave(self, *, now_utc: datetime) -> ConversationParticipant:
        now = require_utc(now_utc, "now_utc")
        if self.left_at_utc is not None:
            raise DomainInvariantError("an inactive participant cannot leave again")
        if now < self.joined_at_utc:
            raise DomainInvariantError("participant time cannot move backwards")
        return ConversationParticipant(
            conversation_id=self.conversation_id,
            character_id=self.character_id,
            joined_at_utc=self.joined_at_utc,
            left_at_utc=now,
        )
