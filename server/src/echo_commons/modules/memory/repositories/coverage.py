import sqlite3

from echo_commons.modules.memory.domain.sources import MemorySource


class CoverageRepository:
    def segment_summary(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        segment_id: str,
        sources: tuple[MemorySource, ...],
    ) -> None:
        connection.executemany(
            "INSERT INTO memory_source_coverage VALUES (?, ?, 'segment_summary', ?, ?, ?, ?) "
            "ON CONFLICT(character_id, owner_kind, owner_id, source_kind, source_id) DO NOTHING",
            [
                (
                    community_id,
                    character_id,
                    segment_id,
                    source.kind.value,
                    source.source_id,
                    source.version,
                )
                for source in sources
            ],
        )
