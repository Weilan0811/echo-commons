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
        existing = connection.execute(
            "SELECT entity_id FROM memory_entity_aliases WHERE character_id=? "
            "AND normalized_alias=? AND invalidated_at_utc IS NULL",
            (batch.character_id, normalized),
        ).fetchone()
        if existing is not None:
            entity_id = existing[0]
        else:
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
        connection.execute(
            "INSERT INTO memory_organization_entities VALUES (?,?,?,?,?,?)",
            (
                batch.character_id,
                batch.batch_id,
                draft.local_id,
                entity_id,
                batch.source_kind,
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
        *,
        subject_entity_id: str | None = None,
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
                batch.source_kind,
                batch.batch_id,
                draft.subject_kind,
                subject_id,
                draft.visibility,
                "1",
                utc_text(now),
            ),
        )
        if subject_entity_id is not None:
            connection.execute(
                "INSERT INTO memory_entry_entities VALUES (?, ?, ?, ?, ?)",
                (batch.character_id, memory_id, subject_entity_id, "subject", utc_text(now)),
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
        if batch.source_kind == "author_material_batch":
            connection.execute(
                "UPDATE memory_author_batches SET outcome=?,consumed_at_utc=? WHERE batch_id=?",
                (outcome, utc_text(now), batch.batch_id),
            )
            return
        connection.executemany(
            "INSERT INTO memory_organization_consumption VALUES (?, ?, ?, ?, ?)",
            [
                (source.segment_id, source.version, batch.batch_id, outcome, utc_text(now))
                for source in batch.sources
            ],
        )
