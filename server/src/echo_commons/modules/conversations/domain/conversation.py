from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from echo_commons.shared.actors import ActorKind, ActorRef


class ConversationKind(StrEnum):
    DIRECT = "direct"
    GROUP = "group"


class ConversationStatus(StrEnum):
    ACTIVE = "active"
    ARCHIVED = "archived"


def validate_members(
    kind: ConversationKind, actors: tuple[ActorRef, ...], *, creating: bool = False
) -> None:
    if not actors or len(set(actors)) != len(actors):
        raise ValueError("Conversation members must be nonempty and unique")
    if creating and kind is ConversationKind.GROUP and len(actors) < 3:
        raise ValueError("Group conversation requires at least three participants")
    if kind is ConversationKind.DIRECT and (
        len(actors) != 2
        or {actor.kind for actor in actors}
        != {
            ActorKind.PLAYER,
            ActorKind.CHARACTER,
        }
    ):
        raise ValueError("Direct conversation requires exactly one player and one character")


@dataclass(frozen=True, slots=True)
class Conversation:
    conversation_id: str
    community_id: str
    kind: ConversationKind
    status: ConversationStatus
    membership_version: int
    next_sequence: int
    created_at_utc: datetime
    updated_at_utc: datetime
    state_version: int = 1
    creator_player_id: str | None = None
    legacy_small_group: bool = False

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ConversationKind(self.kind))
        object.__setattr__(self, "status", ConversationStatus(self.status))
        if not self.conversation_id.strip() or not self.community_id.strip():
            raise ValueError("Conversation identity must be nonempty")
        if self.membership_version < 0 or self.state_version < 1 or self.next_sequence < 1:
            raise ValueError("Conversation versions and sequence are invalid")


@dataclass(frozen=True, slots=True)
class Membership:
    membership_id: str
    community_id: str
    conversation_id: str
    actor: ActorRef
    joined_after_sequence: int
    left_at_sequence: int | None
    joined_at_utc: datetime
    left_at_utc: datetime | None

    def __post_init__(self) -> None:
        if self.joined_after_sequence < 0:
            raise ValueError("Membership sequence must be nonnegative")
        if (self.left_at_sequence is None) != (self.left_at_utc is None):
            raise ValueError("Membership departure requires sequence and time together")
        if self.left_at_sequence is not None and self.left_at_sequence < self.joined_after_sequence:
            raise ValueError("Membership departure precedes joining")
        if self.left_at_utc is not None and self.left_at_utc < self.joined_at_utc:
            raise ValueError("Membership departure time precedes joining")

    def covers(self, sequence: int) -> bool:
        return self.joined_after_sequence < sequence and (
            self.left_at_sequence is None or sequence <= self.left_at_sequence
        )
