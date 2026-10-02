from dataclasses import dataclass
from enum import StrEnum
from typing import TypeAlias

from echo_commons.shared.actors import ActorRef


class SystemSourceKind(StrEnum):
    SYSTEM = "system"


@dataclass(frozen=True, slots=True)
class SystemSource:
    source_id: str
    kind: SystemSourceKind = SystemSourceKind.SYSTEM

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", SystemSourceKind(self.kind))
        if not self.source_id.strip():
            raise ValueError("System message source identity must not be blank")


MessageSource: TypeAlias = ActorRef | SystemSource


def message_source_id(source: MessageSource) -> str:
    return source.actor_id if isinstance(source, ActorRef) else source.source_id
