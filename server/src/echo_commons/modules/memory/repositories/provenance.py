from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.domain.summaries import SummaryBatch, SummaryReference
from echo_commons.shared.errors import ConflictError, NotFoundError


class MemoryProvenanceRepository:
    def context_summaries(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
        *,
        after_sequence: int,
        through_sequence: int,
        recorded_before: datetime,
    ) -> tuple[sqlite3.Row, ...]:
        return tuple(
            connection.execute(
                "SELECT * FROM memory_segments WHERE community_id = ? AND character_id = ? "
                "AND conversation_id = ? AND status = 'ingested' AND summary_version IS NOT NULL "
                "AND last_message_sequence > ? AND last_message_sequence <= ? "
                "AND ingested_at_utc <= ? ORDER BY first_message_sequence DESC LIMIT 8",
                (
                    community_id,
                    character_id,
                    conversation_id,
                    after_sequence,
                    through_sequence,
                    utc_text(recorded_before),
                ),
            )
        )

    def digest_for_batch(
        self, connection: sqlite3.Connection, batch: SummaryBatch
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM conversation_digests WHERE batch_id = ?", (batch.batch_id,)
        ).fetchone()

    def add_digest(
        self,
        connection: sqlite3.Connection,
        batch: SummaryBatch,
        content: str,
        covers_through_sequence: int,
        now: datetime,
    ) -> None:
        connection.execute(
            "INSERT INTO conversation_digests VALUES (?, ?, ?, ?, ?, ?)",
            (str(uuid4()), batch.batch_id, content, "1", covers_through_sequence, utc_text(now)),
        )

    def candidates(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
        after: int,
        through: int,
    ) -> tuple[sqlite3.Row, ...]:
        return tuple(
            connection.execute(
                "SELECT * FROM memory_segments WHERE community_id = ? AND character_id = ? "
                "AND conversation_id = ? AND last_message_sequence > ? "
                "AND last_message_sequence <= ? ORDER BY first_message_sequence, segment_id",
                (community_id, character_id, conversation_id, after, through),
            )
        )

    def organization_consumed(
        self, connection: sqlite3.Connection, segment_id: str, version: str
    ) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM memory_organization_consumption "
                "WHERE segment_id = ? AND summary_version = ?",
                (segment_id, version),
            ).fetchone()
            is not None
        )

    def get_batch(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        batch_id: str,
    ) -> SummaryBatch:
        row = connection.execute(
            "SELECT * FROM memory_summary_batches WHERE community_id = ? "
            "AND character_id = ? AND batch_id = ?",
            (community_id, character_id, batch_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Summary batch does not exist in the character scope")
        sources = tuple(
            SummaryReference(item[0], item[1])
            for item in connection.execute(
                "SELECT segment_id, summary_version FROM memory_summary_batch_items "
                "WHERE batch_id = ? ORDER BY ordinal",
                (batch_id,),
            )
        )
        return SummaryBatch(
            batch_id,
            community_id,
            character_id,
            row["conversation_id"],
            sources,
            row["source_version"],
            row["previous_digest_id"],
        )

    def batch_summaries(
        self, connection: sqlite3.Connection, batch: SummaryBatch
    ) -> tuple[sqlite3.Row, ...]:
        result = []
        for ref in batch.sources:
            row = connection.execute(
                "SELECT * FROM memory_segments WHERE community_id = ? AND character_id = ? "
                "AND conversation_id = ? AND segment_id = ?",
                (batch.community_id, batch.character_id, batch.conversation_id, ref.segment_id),
            ).fetchone()
            if (
                row is None
                or row["status"] != "ingested"
                or row["summary_version"] != ref.version
                or not row["summary_text"]
            ):
                raise ConflictError("Frozen summary batch source is unavailable")
            result.append(row)
        return tuple(result)

    def create_batch(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
        summaries: tuple[sqlite3.Row, ...],
        previous: sqlite3.Row | None,
        now: datetime,
    ) -> SummaryBatch:
        if not summaries:
            raise ValueError("Summary batch requires actual summaries")
        if previous is not None:
            self.get_digest(
                connection, community_id, character_id, conversation_id, previous["digest_id"]
            )
        if any(
            (row["community_id"], row["character_id"], row["conversation_id"], row["status"])
            != (community_id, character_id, conversation_id, "ingested")
            or not row["summary_text"]
            or not row["summary_version"]
            for row in summaries
        ):
            raise ConflictError("Summary batch requires ingested sources from its own scope")
        version = json.dumps(
            {
                "previous_digest": (previous["digest_id"], previous["content_version"])
                if previous
                else None,
                "summaries": [(row["segment_id"], row["summary_version"]) for row in summaries],
            },
            ensure_ascii=False,
            separators=(",", ":"),
        )
        existing = connection.execute(
            "SELECT batch_id FROM memory_summary_batches WHERE community_id = ? "
            "AND character_id = ? AND conversation_id = ? AND source_version = ?",
            (community_id, character_id, conversation_id, version),
        ).fetchone()
        if existing:
            return self.get_batch(connection, community_id, character_id, existing[0])
        batch_id = str(uuid4())
        connection.execute(
            "INSERT INTO memory_summary_batches VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                batch_id,
                community_id,
                character_id,
                conversation_id,
                version,
                previous["digest_id"] if previous else None,
                utc_text(now),
            ),
        )
        connection.executemany(
            "INSERT INTO memory_summary_batch_items VALUES (?, ?, ?, ?)",
            [
                (batch_id, ordinal, row["segment_id"], row["summary_version"])
                for ordinal, row in enumerate(summaries)
            ],
        )
        return self.get_batch(connection, community_id, character_id, batch_id)

    def get_digest(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
        digest_id: str,
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT d.* FROM conversation_digests d JOIN memory_summary_batches b "
            "ON b.batch_id = d.batch_id WHERE b.community_id = ? AND b.character_id = ? "
            "AND b.conversation_id = ? AND d.digest_id = ?",
            (community_id, character_id, conversation_id, digest_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Conversation digest does not exist in the character scope")
        return row

    def latest_digest(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
        *,
        through_sequence: int | None = None,
        recorded_before: datetime | None = None,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT d.* FROM conversation_digests d JOIN memory_summary_batches b "
            "ON b.batch_id = d.batch_id "
            "WHERE b.community_id = ? AND b.character_id = ? AND b.conversation_id = ? "
            "AND (? IS NULL OR d.covers_through_sequence <= ?) "
            "AND (? IS NULL OR d.created_at_utc <= ?) "
            "ORDER BY d.covers_through_sequence DESC, d.created_at_utc DESC LIMIT 1",
            (
                community_id,
                character_id,
                conversation_id,
                through_sequence,
                through_sequence,
                utc_text(recorded_before) if recorded_before else None,
                utc_text(recorded_before) if recorded_before else None,
            ),
        ).fetchone()
