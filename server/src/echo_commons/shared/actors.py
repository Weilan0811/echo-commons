from dataclasses import dataclass
from enum import StrEnum


class ActorKind(StrEnum):
    PLAYER = "player"
    CHARACTER = "character"


@dataclass(frozen=True, slots=True)
class ActorRef:
    kind: ActorKind
    actor_id: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", ActorKind(self.kind))
        if not isinstance(self.actor_id, str) or not self.actor_id.strip():
            raise ValueError("actor_id must be non-empty")


@dataclass(frozen=True, slots=True)
class CommunityScope:
    community_id: str
    character_id: str

    def __post_init__(self) -> None:
        if not self.community_id.strip() or not self.character_id.strip():
            raise ValueError("community and character identities are required")
