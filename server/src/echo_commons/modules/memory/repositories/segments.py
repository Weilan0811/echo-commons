from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.memory.domain.memory import MemorySegment, SegmentStatus
from echo_commons.modules.memory.domain.sources import MemorySource, SourceKind, source_version
from echo_commons.modules.perspective.contracts import ConversationBoundary
from echo_commons.shared.errors import ConflictError, NotFoundError


class SegmentRepository:
    def ingest(self, connection, community_id, character_id, segment_id, summary, now):
        segment = self.get(connection, community_id, character_id, segment_id)
        if segment.status is SegmentStatus.INGESTED:
            if segment.summary_text != summary:
                raise ConflictError("Ingested memory segment already has another result")
            return segment
        if summary is not None and not summary.strip():
            raise ValueError("Memory segment summary must contain text")
        connection.execute(
            "UPDATE memory_segments SET status='ingested',summary_text=?,summary_version=?,"
            "ingested_at_utc=?,updated_at_utc=? WHERE segment_id=?",
            (
                summary,
                "1" if summary is not None else None,
                utc_text(now),
                utc_text(now),
                segment_id,
            ),
        )
        return self.get(connection, community_id, character_id, segment_id)

    def references(self, connection, segment_id, *, context=False):
        table = "memory_segment_context" if context else "memory_segment_sources"
        return tuple(
            MemorySource(SourceKind(row["source_kind"]), row["source_id"], row["source_version"])
            for row in connection.execute(
                f"SELECT * FROM {table} WHERE segment_id=? ORDER BY ordinal", (segment_id,)
            )
        )

    def get(self, connection, community_id, character_id, segment_id) -> MemorySegment:
        row = connection.execute(
            "SELECT * FROM memory_segments WHERE community_id=? AND character_id=? "
            "AND segment_id=?",
            (community_id, character_id, segment_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Memory segment does not exist in the character scope")
        return MemorySegment(
            segment_id,
            community_id,
            character_id,
            row["position"],
            utc_datetime(row["started_at_utc"]),
            utc_datetime(row["ended_at_utc"]),
            tuple(
                ConversationBoundary.model_validate_json(item[0])
                for item in connection.execute(
                    "SELECT boundary_json FROM memory_segment_scenes WHERE segment_id=? "
                    "ORDER BY conversation_id",
                    (segment_id,),
                )
            ),
            SegmentStatus(row["status"]),
            row["source_version"],
            self.references(connection, segment_id),
            utc_datetime(row["sealed_at_utc"]),
            row["summary_text"],
            row["summary_version"],
            self.references(connection, segment_id, context=True),
            row["activity_participation_id"],
        )

    def covered_messages(self, connection, community_id, character_id) -> frozenset[str]:
        return frozenset(
            row[0]
            for row in connection.execute(
                "SELECT s.source_id FROM memory_segment_sources s "
                "JOIN memory_segments m USING(segment_id) WHERE m.community_id=? AND "
                "m.character_id=? "
                "AND s.source_kind='message'",
                (community_id, character_id),
            )
        )

    def add(
        self,
        connection,
        community_id,
        character_id,
        messages,
        sources,
        boundaries,
        context,
        now,
        *,
        occurred_at=(),
        activity_participation_id=None,
    ):
        segment_id = str(uuid4())
        position = connection.execute(
            "SELECT COALESCE(max(position),0)+1 FROM memory_segments WHERE character_id=?",
            (character_id,),
        ).fetchone()[0]
        connection.execute(
            "INSERT INTO memory_segments (segment_id,community_id,character_id,position,"
            "started_at_utc,ended_at_utc,status,source_version,sealed_at_utc,created_at_utc,"
            "updated_at_utc) VALUES (?,?,?,?,?,?,'sealed',?,?,?,?)",
            (
                segment_id,
                community_id,
                character_id,
                position,
                utc_text(min((*occurred_at, *(m.created_at_utc for m in messages)))),
                utc_text(max((*occurred_at, *(m.created_at_utc for m in messages)))),
                source_version((*sources, *context)),
                utc_text(now),
                utc_text(now),
                utc_text(now),
            ),
        )
        if activity_participation_id is not None:
            connection.execute(
                "UPDATE memory_segments SET activity_participation_id=? WHERE segment_id=?",
                (activity_participation_id, segment_id),
            )
        for boundary in boundaries:
            selected = tuple(m for m in messages if m.conversation_id == boundary.conversation_id)
            if not selected and activity_participation_id is None:
                continue
            frozen = boundary.model_copy(
                update={
                    "upper_sequence": max(
                        (m.sequence for m in selected), default=boundary.upper_sequence
                    )
                }
            )
            connection.execute(
                "INSERT INTO memory_segment_scenes VALUES (?,?,?,?,?)",
                (
                    segment_id,
                    boundary.conversation_id,
                    min((m.sequence for m in selected), default=boundary.upper_sequence),
                    frozen.upper_sequence,
                    frozen.model_dump_json(),
                ),
            )
        for table, references in (
            ("memory_segment_sources", sources),
            ("memory_segment_context", context),
        ):
            connection.executemany(
                f"INSERT INTO {table} VALUES (?,?,?,?,?)",
                [
                    (segment_id, s.kind.value, s.source_id, s.version, ordinal)
                    for ordinal, s in enumerate(references)
                ],
            )
        for source in sources:
            if source.kind is SourceKind.THOUGHT:
                connection.execute(
                    "UPDATE thoughts SET segment_id=? WHERE thought_id=? AND character_id=? "
                    "AND segment_id IS NULL",
                    (segment_id, source.source_id, character_id),
                )
        return self.get(connection, community_id, character_id, segment_id)

    def scenes(self, connection, segment_id):
        return tuple(
            dict(row)
            for row in connection.execute(
                "SELECT * FROM memory_segment_scenes WHERE segment_id=? ORDER BY conversation_id",
                (segment_id,),
            )
        )

    def covered(self, connection, community, character, segment_ids):
        found = set()
        for identity in segment_ids:
            self.get(connection, community, character, identity)
            found.update(
                source.source_id
                for source in self.references(connection, identity)
                if source.kind is SourceKind.MESSAGE
            )
        return frozenset(found)
