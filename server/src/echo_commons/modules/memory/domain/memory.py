from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from echo_commons.modules.memory.domain.sources import MemorySource


class SegmentStatus(StrEnum):
    SEALED = "sealed"
    INGESTED = "ingested"


@dataclass(frozen=True, slots=True)
class MemorySegment:
    segment_id: str
    community_id: str
    character_id: str
    conversation_id: str
    first_sequence: int
    last_sequence: int
    status: SegmentStatus
    source_version: str
    sources: tuple[MemorySource, ...]
    sealed_at_utc: datetime
    summary_text: str | None = None
    summary_version: str | None = None
