import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.domain.batches import AuthorBatch
from echo_commons.modules.memory.domain.organization import MemoryEntryDraft
from echo_commons.modules.memory.domain.summaries import SummaryBatch


class MemoryOrganizationRepository:
    def entry(
        self,
        connection: sqlite3.Connection,
        batch: SummaryBatch | AuthorBatch,
        draft: MemoryEntryDraft,
        now: datetime,
    ) -> str:
        memory_id = str(uuid4())
        connection.execute(
            "INSERT INTO memory_entries "
            "(memory_id,community_id,character_id,memory_kind,content,confidence,"
            "salience,source_kind,source_ref,visibility,content_version,recorded_at_utc) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?)",
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
                draft.visibility,
                "1",
                utc_text(now),
            ),
        )
        connection.executemany(
            "INSERT INTO memory_entry_sources VALUES (?,?,?,?,?)",
            [
                (batch.character_id, memory_id, source.kind, source.source_id, source.version)
                for source in draft.sources
            ],
        )
        return memory_id

    def consume(
        self,
        connection: sqlite3.Connection,
        batch: SummaryBatch | AuthorBatch,
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
