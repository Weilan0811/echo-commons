import json
import sqlite3
from datetime import datetime

from echo_commons.modules.memory.domain.organization import (
    CognitionOperation,
    FactOperation,
    MemoryRecordRef,
    OrganizationEvidence,
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
        facts: tuple[FactOperation, ...],
        cognitions: tuple[CognitionOperation, ...],
        sources: tuple[OrganizationEvidence, ...],
        cognitions_complete: bool,
        observed_at: datetime,
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
            frozen = connection.execute(
                "SELECT organization_sources_json FROM memory_summary_batches WHERE batch_id=?",
                (batch_id,),
            ).fetchone()[0]
            if frozen is None:
                raise ConflictError("Long-term batch requires original sources")
            allowed = {tuple(item) for item in json.loads(frozen)}
        by_ref = {
            f"{source.kind}:{source.source_id}": source
            for source in sources
            if (source.kind, source.source_id, source.version) in allowed
        }
        if len(by_ref) != len(sources):
            raise ConflictError("Original source is outside the frozen batch")

        def evidence(references, permitted):
            if any(ref not in by_ref or by_ref[ref].kind not in permitted for ref in references):
                raise ConflictError("Long-term evidence has the wrong source qualification")
            return tuple(by_ref[ref] for ref in dict.fromkeys(references))

        mapping = self.repository.stage(connection, batch, "facts")
        changes = MemoryChangeRepository()
        if mapping is None:
            mapping = {}
            for operation in facts:
                ref = self.repository.fact(
                    connection,
                    batch,
                    operation,
                    evidence(operation.evidence_refs, {"message", "author_chunk"}),
                    observed_at,
                    now,
                )
                mapping[operation.local_key] = ref.model_dump(mode="json")
                changes.record(
                    connection,
                    community_id,
                    character_id,
                    "memory_fact",
                    ref.memory_id,
                    ref.version,
                    now,
                )
            self.repository.complete_stage(
                connection,
                batch,
                "facts",
                mapping,
                tuple(source for source in sources if source.kind != "thought"),
                now,
            )
        if cognitions_complete and self.repository.stage(connection, batch, "cognitions") is None:
            written = []
            for operation in cognitions:
                supports = []
                for support in operation.supporting_facts:
                    if support.kind == "candidate":
                        if support.local_key not in mapping:
                            raise ConflictError("Reviewed fact mapping is unavailable")
                        supports.append(MemoryRecordRef.model_validate(mapping[support.local_key]))
                    else:
                        supports.append(
                            MemoryRecordRef(
                                record_kind="fact",
                                memory_id=support.memory_id,
                                version=support.version,
                            )
                        )
                ref = self.repository.cognition(
                    connection,
                    batch,
                    operation,
                    evidence(operation.evidence_refs, {"thought", "author_chunk"}),
                    tuple(dict.fromkeys(supports)),
                    now,
                )
                written.append(ref.model_dump(mode="json"))
                changes.record(
                    connection,
                    community_id,
                    character_id,
                    "memory_cognition",
                    ref.memory_id,
                    ref.version,
                    now,
                )
            self.repository.complete_stage(connection, batch, "cognitions", written, sources, now)
            self.repository.consume(
                connection, batch, "completed" if mapping or written else "no_op", now
            )
        self.indexing.memories(connection, community_id, character_id, now)
