from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum

from echo_commons.modules.memory.domain.sources import MemorySource
from echo_commons.modules.perspective.contracts import ConversationBoundary


class SegmentStatus(StrEnum):
    SEALED = "sealed"
    INGESTED = "ingested"


@dataclass(frozen=True, slots=True)
class MemorySegment:
    segment_id: str
    community_id: str
    character_id: str
    position: int
    started_at_utc: datetime
    ended_at_utc: datetime
    conversations: tuple[ConversationBoundary, ...]
    status: SegmentStatus
    source_version: str
    sources: tuple[MemorySource, ...]
    sealed_at_utc: datetime
    summary_text: str | None = None
    summary_version: str | None = None
    context_sources: tuple[MemorySource, ...] = ()
    activity_participation_id: str | None = None
