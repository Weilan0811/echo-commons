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
        *,
        organization_sources: tuple | None = None,
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
                **(
                    {"organization_sources": organization_sources}
                    if organization_sources is not None
                    else {}
                ),
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
            "INSERT INTO memory_summary_batches VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                batch_id,
                community_id,
                character_id,
                conversation_id,
                version,
                previous["digest_id"] if previous else None,
                utc_text(now),
                json.dumps(organization_sources) if organization_sources is not None else None,
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

    def progress(self, connection, community, character):
        row = connection.execute(
            "SELECT item.value FROM memory_change_batches b "
            "JOIN memory_core_refreshes progress USING(batch_id),json_each(b.materials_json) item "
            "WHERE b.community_id=? AND b.character_id=? "
            "AND progress.outcome IN ('completed','no_op') "
            "AND json_extract(item.value,'$.fact_kind')='core_memory_request' "
            "ORDER BY b.created_at_utc DESC,b.batch_id DESC LIMIT 1",
            (community, character),
        ).fetchone()
        if row is None:
            return None
        request = json.loads(json.loads(row[0])["content"])
        return request if request["unread_memory_ids"] else None

    def record_sources(self, connection, community, character, record_kind, memory_id, version):
        table = {"fact": "memory_facts", "cognition": "memory_cognitions"}[record_kind]
        record = connection.execute(
            f"SELECT * FROM {table} WHERE community_id=? AND character_id=? "
            f"AND memory_id=? AND version=?",
            (community, character, memory_id, version),
        ).fetchone()
        if record is None:
            raise NotFoundError("Long-term record does not exist in this character scope")
        found = []
        source_table = {"fact": "memory_fact_sources", "cognition": "memory_cognition_sources"}[
            record_kind
        ]
        for reference in connection.execute(
            f"SELECT * FROM {source_table} WHERE memory_id=? AND version=? "
            "ORDER BY source_kind,source_id,source_version",
            (memory_id, version),
        ):
            if reference["source_kind"] == "message":
                row = connection.execute(
                    "SELECT text content,'1' version FROM messages WHERE "
                    "community_id=? AND message_id=?",
                    (community, reference["source_id"]),
                ).fetchone()
            elif reference["source_kind"] == "thought":
                row = connection.execute(
                    "SELECT content,content_version version FROM thoughts WHERE community_id=? "
                    "AND character_id=? AND thought_id=?",
                    (community, character, reference["source_id"]),
                ).fetchone()
            else:
                row = connection.execute(
                    "SELECT c.content,m.question,m.blueprint_version version "
                    "FROM memory_author_chunks c "
                    "JOIN memory_author_materials m USING(material_id) "
                    "JOIN character_instances i USING(character_id) WHERE i.community_id=? "
                    "AND m.character_id=? AND c.chunk_id=?",
                    (community, character, reference["source_id"]),
                ).fetchone()
                if row is not None and row["question"]:
                    row = {
                        "content": f"问题：{row['question']}\n回答：{row['content']}",
                        "version": row["version"],
                    }
            readable = bool(
                row is not None and row["version"] == reference["source_version"] and row["content"]
            )
            found.append(
                dict(
                    source_kind=reference["source_kind"],
                    source_id=reference["source_id"],
                    source_version=reference["source_version"],
                    readable=readable,
                    content=row["content"] if readable else None,
                )
            )
        if record_kind == "cognition":
            for support in connection.execute(
                "SELECT s.*,f.content,f.status FROM memory_cognition_fact_supports s "
                "JOIN memory_facts f ON f.memory_id=s.fact_id AND f.version=s.fact_version "
                "WHERE s.memory_id=? AND s.version=? AND f.community_id=? AND f.character_id=?",
                (memory_id, version, community, character),
            ):
                original = self.record_sources(
                    connection,
                    community,
                    character,
                    "fact",
                    support["fact_id"],
                    support["fact_version"],
                )
                readable = (
                    support["status"] in ("current", "superseded")
                    and bool(original)
                    and all(item["readable"] for item in original)
                )
                found.append(
                    dict(
                        source_kind="memory_fact",
                        source_id=support["fact_id"],
                        source_version=str(support["fact_version"]),
                        readable=readable,
                        content=support["content"] if readable else None,
                    )
                )
        return found

    def view(self, connection, community, character, view_kind):
        return connection.execute(
            "SELECT * FROM memory_views WHERE community_id=? AND character_id=? AND view_kind=?",
            (community, character, view_kind),
        ).fetchone()
