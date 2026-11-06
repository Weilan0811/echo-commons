import json
from dataclasses import dataclass
from enum import StrEnum


class SourceKind(StrEnum):
    MESSAGE = "message"
    THOUGHT = "thought"
    GAME_EVENT = "game_event"


@dataclass(frozen=True, slots=True)
class MemorySource:
    kind: SourceKind
    source_id: str
    version: str


def source_version(sources: tuple[MemorySource, ...]) -> str:
    return json.dumps(
        [(source.kind.value, source.source_id, source.version) for source in sources],
        ensure_ascii=False,
        separators=(",", ":"),
    )
