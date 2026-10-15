import sqlite3
from datetime import datetime

from echo_commons.modules.memory.domain.memory import MemorySegment
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.materials import MemoryMaterials


class MemoryIngestion:
    def __init__(self, segments: SegmentRepository, coverage: CoverageRepository) -> None:
        self.segments, self.coverage = segments, coverage

    def ingest(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        segment_id: str,
        summary: str | None,
        now: datetime,
    ) -> MemorySegment:
        segment = self.segments.ingest(
            connection, community_id, character_id, segment_id, summary, now
        )
        self.coverage.segment_summary(
            connection, community_id, character_id, segment_id, segment.sources
        )
        if summary is not None:
            MemoryMaterials(SearchRepository()).summaries(
                connection, community_id, character_id, now
            )
        return segment
