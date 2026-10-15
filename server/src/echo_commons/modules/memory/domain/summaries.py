from dataclasses import dataclass
from datetime import datetime
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
    sources: tuple[SummaryReference, ...]
    source_version: str
    previous_digest_ids: tuple[str, ...]
    created_at_utc: datetime
    source_kind: str = "memory_summary_batch"
