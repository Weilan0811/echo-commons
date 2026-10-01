import hashlib
import json
from dataclasses import dataclass
from enum import StrEnum

from echo_commons.domain.errors import DomainInvariantError, require_non_empty


class MemorySourceKind(StrEnum):
    MESSAGE = "message"
    THOUGHT = "thought"
    SEGMENT_SUMMARY = "segment_summary"


@dataclass(frozen=True, slots=True)
class MemorySourceRef:
    kind: MemorySourceKind
    source_id: str
    version: str

    def __post_init__(self) -> None:
        object.__setattr__(self, "kind", MemorySourceKind(self.kind))
        require_non_empty(self.source_id, "source_id")
        require_non_empty(self.version, "version")


def content_version(value: object) -> str:
    return hashlib.sha256(
        json.dumps(value, ensure_ascii=False, sort_keys=True, separators=(",", ":")).encode()
    ).hexdigest()


@dataclass(frozen=True, slots=True)
class SummaryBatch:
    batch_id: str
    account_id: str
    conversation_id: str
    character_id: str
    sources: tuple[MemorySourceRef, ...]
    source_version: str
    previous_digest_id: str | None

    def __post_init__(self) -> None:
        for field in (
            "batch_id",
            "account_id",
            "conversation_id",
            "character_id",
            "source_version",
        ):
            require_non_empty(getattr(self, field), field)
        if not self.sources or any(
            s.kind is not MemorySourceKind.SEGMENT_SUMMARY for s in self.sources
        ):
            raise DomainInvariantError("summary batch requires summary sources")
        if len({s.source_id for s in self.sources}) != len(self.sources):
            raise DomainInvariantError("summary batch sources must be unique")
