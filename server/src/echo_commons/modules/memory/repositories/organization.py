import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.domain.organization import (
    MemoryEdgeDraft,
    MemoryEntityDraft,
    MemoryEntryDraft,
    normalize_alias,
)
from echo_commons.modules.memory.domain.summaries import SummaryBatch


class MemoryOrganizationRepository:
    def entity(
        self,
        connection: sqlite3.Connection,
        batch: SummaryBatch,
        draft: MemoryEntityDraft,
        now: datetime,
    ) -> str:
        normalized = normalize_alias(draft.canonical_name)
        row = connection.execute(
            "SELECT e.entity_id FROM memory_entities e JOIN memory_entity_aliases a "
            "ON a.entity_id = e.entity_id AND a.character_id = e.character_id "
            "WHERE e.community_id = ? AND e.character_id = ? "
            "AND a.normalized_alias = ? AND e.invalidated_at_utc IS NULL "
            "AND a.invalidated_at_utc IS NULL ORDER BY e.created_at_utc, e.entity_id LIMIT 1",
            (batch.community_id, batch.character_id, normalized),
        ).fetchone()
        if row is not None:
            return row[0]
        entity_id = str(uuid4())
        connection.execute(
            "INSERT INTO memory_entities VALUES (?, ?, ?, ?, ?, ?, ?, NULL)",
            (
                entity_id,
                batch.community_id,
                batch.character_id,
                draft.entity_kind,
                draft.canonical_name,
                utc_text(now),
                utc_text(now),
            ),
        )
        connection.execute(
            "INSERT INTO memory_entity_aliases VALUES (?, ?, ?, ?, ?, ?, NULL)",
            (
                str(uuid4()),
                batch.character_id,
                entity_id,
                draft.canonical_name,
                normalized,
                utc_text(now),
            ),
        )
        return entity_id

    def entry(
        self,
        connection: sqlite3.Connection,
        batch: SummaryBatch,
        draft: MemoryEntryDraft,
        subject_id: str,
        now: datetime,
    ) -> str:
        memory_id = str(uuid4())
        connection.execute(
            "INSERT INTO memory_entries "
            "(memory_id, community_id, character_id, memory_kind, content, confidence, "
            "salience, source_kind, source_ref, subject_kind, subject_id, visibility, "
            "content_version, recorded_at_utc) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                memory_id,
                batch.community_id,
                batch.character_id,
                draft.memory_kind,
                draft.content,
                draft.confidence,
                draft.salience,
                "memory_summary_batch",
                batch.batch_id,
                draft.subject_kind,
                subject_id,
                draft.visibility,
                "1",
                utc_text(now),
            ),
        )
        if draft.subject_kind == "entity":
            connection.execute(
                "INSERT INTO memory_entry_entities VALUES (?, ?, ?, ?, ?)",
                (batch.character_id, memory_id, subject_id, "subject", utc_text(now)),
            )
        return memory_id

    def edge(
        self,
        connection: sqlite3.Connection,
        batch: SummaryBatch,
        draft: MemoryEdgeDraft,
        from_id: str,
        to_id: str,
        now: datetime,
    ) -> None:
        existing = connection.execute(
            "SELECT edge_id FROM memory_edges WHERE character_id = ? AND from_entity_id = ? "
            "AND to_entity_id = ? AND edge_kind = ? AND source_memory_id IS NULL "
            "AND invalidated_at_utc IS NULL",
            (batch.character_id, from_id, to_id, draft.edge_kind),
        ).fetchone()
        if existing is not None:
            connection.execute(
                "UPDATE memory_edges SET confidence = ? WHERE edge_id = ?",
                (draft.confidence, existing[0]),
            )
            return
        connection.execute(
            "INSERT INTO memory_edges VALUES (?, ?, ?, ?, ?, ?, NULL, ?, NULL)",
            (
                str(uuid4()),
                batch.character_id,
                from_id,
                to_id,
                draft.edge_kind,
                draft.confidence,
                utc_text(now),
            ),
        )

    def consume(
        self,
        connection: sqlite3.Connection,
        batch: SummaryBatch,
        outcome: str,
        now: datetime,
    ) -> None:
        connection.executemany(
            "INSERT INTO memory_organization_consumption VALUES (?, ?, ?, ?, ?)",
            [
                (source.segment_id, source.version, batch.batch_id, outcome, utc_text(now))
                for source in batch.sources
            ],
        )
