import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.memory.domain.memory import MemorySegment, SegmentStatus
from echo_commons.modules.memory.domain.sources import MemorySource, SourceKind, source_version
from echo_commons.shared.errors import ConflictError, NotFoundError


class SegmentRepository:
    def ingest(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        segment_id: str,
        summary: str | None,
        now: datetime,
    ) -> MemorySegment:
        segment = self.get(connection, community_id, character_id, segment_id)
        if segment.status is SegmentStatus.INGESTED:
            if segment.summary_text != summary:
                raise ConflictError("Ingested memory segment already has another result")
            return segment
        if summary is not None and not summary.strip():
            raise ValueError("Memory segment summary must contain text")
        connection.execute(
            "UPDATE memory_segments SET status = 'ingested', summary_text = ?, "
            "summary_version = ?, ingested_at_utc = ?, updated_at_utc = ? "
            "WHERE community_id = ? AND character_id = ? AND segment_id = ?",
            (
                summary,
                "1" if summary is not None else None,
                utc_text(now),
                utc_text(now),
                community_id,
                character_id,
                segment_id,
            ),
        )
        return self.get(connection, community_id, character_id, segment_id)

    def get(
        self, connection: sqlite3.Connection, community_id: str, character_id: str, segment_id: str
    ) -> MemorySegment:
        row = connection.execute(
            "SELECT * FROM memory_segments WHERE community_id = ? AND character_id = ? "
            "AND segment_id = ?",
            (community_id, character_id, segment_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Memory segment does not exist in the character scope")
        sources = tuple(
            MemorySource(SourceKind(item["source_kind"]), item["source_id"], item["source_version"])
            for item in connection.execute(
                "SELECT * FROM memory_segment_sources WHERE segment_id = ? ORDER BY ordinal",
                (segment_id,),
            )
        )
        return MemorySegment(
            segment_id,
            community_id,
            character_id,
            row["conversation_id"],
            row["first_message_sequence"],
            row["last_message_sequence"],
            SegmentStatus(row["status"]),
            row["source_version"],
            sources,
            utc_datetime(row["sealed_at_utc"]),
            row["summary_text"],
            row["summary_version"],
        )

    def covered_messages(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
    ) -> frozenset[str]:
        return frozenset(
            row[0]
            for row in connection.execute(
                "SELECT s.source_id FROM memory_segment_sources s "
                "JOIN memory_segments m ON m.segment_id = s.segment_id "
                "WHERE m.community_id = ? AND m.character_id = ? AND m.conversation_id = ? "
                "AND s.source_kind = 'message'",
                (community_id, character_id, conversation_id),
            )
        )

    def next_start(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
        after: int,
    ) -> int | None:
        return connection.execute(
            "SELECT MIN(first_message_sequence) FROM memory_segments "
            "WHERE community_id = ? AND character_id = ? AND conversation_id = ? "
            "AND first_message_sequence > ?",
            (community_id, character_id, conversation_id, after),
        ).fetchone()[0]

    def add(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
        first_sequence: int,
        last_sequence: int,
        sources: tuple[MemorySource, ...],
        now: datetime,
    ) -> MemorySegment:
        segment_id = str(uuid4())
        connection.execute(
            "INSERT INTO memory_segments "
            "(segment_id, community_id, character_id, conversation_id, first_message_sequence, "
            "last_message_sequence, status, source_version, sealed_at_utc, created_at_utc, "
            "updated_at_utc) VALUES (?, ?, ?, ?, ?, ?, 'sealed', ?, ?, ?, ?)",
            (
                segment_id,
                community_id,
                character_id,
                conversation_id,
                first_sequence,
                last_sequence,
                source_version(sources),
                utc_text(now),
                utc_text(now),
                utc_text(now),
            ),
        )
        connection.executemany(
            "INSERT INTO memory_segment_sources VALUES (?, ?, ?, ?, ?)",
            [
                (segment_id, source.kind.value, source.source_id, source.version, ordinal)
                for ordinal, source in enumerate(sources)
            ],
        )
        for source in sources:
            if source.kind is SourceKind.THOUGHT:
                connection.execute(
                    "UPDATE thoughts SET segment_id = ? WHERE thought_id = ? "
                    "AND community_id = ? AND character_id = ? AND segment_id IS NULL",
                    (segment_id, source.source_id, community_id, character_id),
                )
        return self.get(connection, community_id, character_id, segment_id)
