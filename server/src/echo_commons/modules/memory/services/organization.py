import sqlite3
from datetime import datetime

from echo_commons.modules.memory.domain.organization import (
    MemoryEdgeDraft,
    MemoryEntityDraft,
    MemoryEntryDraft,
    normalize_alias,
)
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
        entities: tuple[MemoryEntityDraft, ...],
        edges: tuple[MemoryEdgeDraft, ...],
        no_op: bool,
        now: datetime,
    ) -> None:
        batch = self.provenance.get_batch(connection, community_id, character_id, batch_id)
        self.provenance.batch_summaries(connection, batch)
        if any(
            self.provenance.organization_consumed(connection, source.segment_id, source.version)
            for source in batch.sources
        ):
            raise ConflictError("Memory organization source has already been consumed")
        identifiers = {entity.local_id for entity in entities}
        if any(not normalize_alias(entity.canonical_name) for entity in entities):
            raise ConflictError("Memory organization entity name must contain text")
        if len(identifiers) != len(entities):
            raise ConflictError("Memory organization entities contain duplicate identities")
        if any(
            edge.from_local_id not in identifiers or edge.to_local_id not in identifiers
            for edge in edges
        ):
            raise ConflictError("Memory organization references an unknown entity")
        if no_op and (entries or entities or edges):
            raise ConflictError("Memory organization no-op contains facts")
        resolved = {
            entity.local_id: self.repository.entity(connection, batch, entity, now)
            for entity in entities
        }
        for entry in entries:
            subject = (
                resolved.get(entry.subject_id, entry.subject_id)
                if entry.subject_kind == "entity"
                else entry.subject_id
            )
            self.repository.entry(
                connection,
                batch,
                entry,
                subject,
                now,
                subject_entity_id=resolved.get(entry.subject_id),
            )
        for edge in edges:
            self.repository.edge(
                connection,
                batch,
                edge,
                resolved[edge.from_local_id],
                resolved[edge.to_local_id],
                now,
            )
        self.repository.consume(connection, batch, "no_op" if no_op else "completed", now)
        self.indexing.memories(connection, community_id, character_id, now)
