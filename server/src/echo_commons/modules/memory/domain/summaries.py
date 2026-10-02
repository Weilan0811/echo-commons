from dataclasses import dataclass
from enum import StrEnum


class SummaryConsumer(StrEnum):
    CONTINUITY = "continuity_compress"
    ORGANIZATION = "memory_organize"


@dataclass(frozen=True, slots=True)
class SummaryReference:
    segment_id: str
    version: str


@dataclass(frozen=True, slots=True)
class SummaryBatch:
    batch_id: str
    community_id: str
    character_id: str
    conversation_id: str
    sources: tuple[SummaryReference, ...]
    source_version: str
    previous_digest_id: str | None
