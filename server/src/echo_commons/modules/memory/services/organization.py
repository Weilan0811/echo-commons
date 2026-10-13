import sqlite3
from datetime import datetime

from echo_commons.modules.memory.domain.organization import (
    MemoryEntryDraft,
)
from echo_commons.modules.memory.repositories.author_batches import AuthorBatchRepository
from echo_commons.modules.memory.repositories.changes import MemoryChangeRepository
from echo_commons.modules.memory.repositories.organization import MemoryOrganizationRepository
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.modules.memory.services.indexing import MemoryIndexing
from echo_commons.shared.errors import ConflictError


class MemoryOrganization:
    def __init__(
        self,
        provenance: MemoryProvenanceRepository,
        repository: MemoryOrganizationRepository,
        indexing: MemoryIndexing,
    ) -> None:
        self.provenance, self.repository, self.indexing = provenance, repository, indexing

    def organize(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        batch_id: str,
        entries: tuple[MemoryEntryDraft, ...],
        no_op: bool,
        now: datetime,
    ) -> None:
        author_row = connection.execute(
            "SELECT outcome FROM memory_author_batches WHERE batch_id=? AND character_id=?",
            (batch_id, character_id),
        ).fetchone()
        if author_row is not None:
            authors = AuthorBatchRepository()
            batch = authors.get(connection, community_id, character_id, batch_id)
            rows = authors.materials(connection, batch)
            allowed = {("author_chunk", row["chunk_id"], row["blueprint_version"]) for row in rows}
            if author_row["outcome"] is not None:
                raise ConflictError("Author materials have already been consumed")
        else:
            batch = self.provenance.get_batch(connection, community_id, character_id, batch_id)
            rows = self.provenance.batch_summaries(connection, batch)
            allowed = {
                ("segment_summary", row["segment_id"], row["summary_version"]) for row in rows
            }
        if author_row is None and any(
            self.provenance.organization_consumed(connection, source.segment_id, source.version)
            for source in batch.sources
        ):
            raise ConflictError("Memory organization source has already been consumed")
        if no_op and entries:
            raise ConflictError("Memory organization no-op contains pages")
        if not no_op and not entries:
            raise ConflictError("Memory organization requires pages or explicit no-op")
        if any(not entry.sources for entry in entries):
            raise ConflictError("Memory page requires individual evidence")
        if any(
            (source.kind, source.source_id, source.version) not in allowed
            for entry in entries
            for source in entry.sources
        ):
            raise ConflictError("Memory page evidence is outside the frozen batch")
        for entry in entries:
            memory_id = self.repository.entry(connection, batch, entry, now)
            MemoryChangeRepository().record(
                connection, community_id, character_id, "memory_entry", memory_id, "1", now
            )
        self.repository.consume(connection, batch, "no_op" if no_op else "completed", now)
        self.indexing.memories(connection, community_id, character_id, now)
