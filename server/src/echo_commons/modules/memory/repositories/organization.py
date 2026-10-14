import json
import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.domain.batches import AuthorBatch
from echo_commons.modules.memory.domain.organization import (
    CognitionReplace,
    FactAdd,
    FactCorrect,
    FactSupport,
    MemoryFactContent,
    MemoryRecordRef,
)
from echo_commons.modules.memory.domain.summaries import SummaryBatch
from echo_commons.modules.memory.repositories.records import LongTermMemoryRepository
from echo_commons.shared.errors import ConflictError


class MemoryOrganizationRepository:
    def current(self, connection, batch, reference):
        row = LongTermMemoryRepository().get(
            connection, batch.community_id, batch.character_id, reference
        )
        if row["status"] not in ("current", "needs_review"):
            raise ConflictError("Long-term record version has changed")
        return row

    def fact(self, connection, batch, operation, sources, learned_at, now):
        learned_at = max(
            (source.known_at_utc for source in sources if source.known_at_utc), default=learned_at
        )
        if isinstance(operation, FactAdd):
            identity, version, content = str(uuid4()), 1, operation.fact
            previous_sources = ()
        else:
            if operation.previous.record_kind != "fact":
                raise ConflictError("Fact operation requires a fact reference")
            previous = self.current(connection, batch, operation.previous)
            if isinstance(operation, FactSupport):
                learned_at = max(learned_at, datetime.fromisoformat(previous["learned_at_utc"]))
            identity, version = previous["memory_id"], previous["version"] + 1
            content = (
                operation.fact
                if isinstance(operation, FactCorrect)
                else MemoryFactContent(
                    topic=previous["topic"],
                    content=previous["content"],
                    participants=json.loads(previous["participants_json"]),
                    occurred_at_utc=previous["occurred_at_utc"],
                    conditions=previous["conditions"],
                    salience=previous["salience"],
                )
            )
            previous_sources = (
                tuple(
                    connection.execute(
                        "SELECT source_kind,source_id,source_version FROM memory_fact_sources "
                        "WHERE memory_id=? AND version=?",
                        (identity, previous["version"]),
                    )
                )
                if isinstance(operation, FactSupport)
                else ()
            )
            connection.execute(
                "UPDATE memory_facts SET status=? WHERE memory_id=? AND version=?",
                (
                    "invalid" if isinstance(operation, FactCorrect) else "superseded",
                    identity,
                    previous["version"],
                ),
            )
            if isinstance(operation, FactCorrect):
                connection.execute(
                    "UPDATE memory_cognitions SET status='needs_review' WHERE status='current' "
                    "AND (memory_id,version) IN (SELECT memory_id,version "
                    "FROM memory_cognition_fact_supports WHERE fact_id=?)",
                    (identity,),
                )
        connection.execute(
            "INSERT INTO memory_facts VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,'current')",
            (
                identity,
                version,
                batch.community_id,
                batch.character_id,
                content.topic,
                content.content,
                json.dumps(
                    [
                        {"kind": item.kind.value, "actor_id": item.actor_id}
                        for item in content.participants
                    ]
                ),
                content.conditions,
                utc_text(content.occurred_at_utc) if content.occurred_at_utc else None,
                utc_text(learned_at),
                content.salience,
                batch.source_kind,
                batch.batch_id,
                utc_text(now),
            ),
        )
        all_sources = {tuple(row) for row in previous_sources}
        all_sources.update((source.kind, source.source_id, source.version) for source in sources)
        connection.executemany(
            "INSERT INTO memory_fact_sources VALUES (?,?,?,?,?)",
            [(identity, version, *source) for source in sorted(all_sources)],
        )
        return MemoryRecordRef(record_kind="fact", memory_id=identity, version=version)

    def cognition(self, connection, batch, operation, sources, facts, now):
        if not sources and not facts:
            raise ConflictError("Cognition requires original or fact support")
        if isinstance(operation, CognitionReplace):
            if operation.previous.record_kind != "cognition":
                raise ConflictError("Cognition replacement requires a cognition reference")
            previous = self.current(connection, batch, operation.previous)
            identity, version = previous["memory_id"], previous["version"] + 1
            connection.execute(
                "UPDATE memory_cognitions SET status='superseded' WHERE memory_id=? AND version=?",
                (identity, previous["version"]),
            )
        else:
            identity, version = str(uuid4()), 1
        for fact in facts:
            row = LongTermMemoryRepository().get(
                connection, batch.community_id, batch.character_id, fact
            )
            if row["status"] not in ("current", "superseded"):
                raise ConflictError("Cognition support fact is invalid")
        content = operation.cognition
        connection.execute(
            "INSERT INTO memory_cognitions VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,'current')",
            (
                identity,
                version,
                batch.community_id,
                batch.character_id,
                content.topic,
                content.content,
                utc_text(now),
                content.applies_to,
                json.dumps(content.model_dump(mode="json")["target"]) if content.target else None,
                content.salience,
                batch.source_kind,
                batch.batch_id,
                utc_text(now),
            ),
        )
        connection.executemany(
            "INSERT INTO memory_cognition_sources VALUES (?,?,?,?,?)",
            [
                (identity, version, source.kind, source.source_id, source.version)
                for source in sources
            ],
        )
        connection.executemany(
            "INSERT INTO memory_cognition_fact_supports VALUES (?,?,?,?)",
            [(identity, version, fact.memory_id, fact.version) for fact in facts],
        )
        return MemoryRecordRef(record_kind="cognition", memory_id=identity, version=version)

    def stage(self, connection, batch, stage):
        row = connection.execute(
            "SELECT * FROM memory_organization_stages WHERE character_id=? "
            "AND batch_id=? AND stage=?",
            (batch.character_id, batch.batch_id, stage),
        ).fetchone()
        return json.loads(row["references_json"]) if row else None

    def complete_stage(self, connection, batch, stage, references, sources, now):
        connection.execute(
            "INSERT INTO memory_organization_stages VALUES (?,?,?,?,?,?,?)",
            (
                batch.community_id,
                batch.character_id,
                batch.batch_id,
                stage,
                "completed" if references else "no_op",
                json.dumps(references),
                utc_text(now),
            ),
        )
        connection.executemany(
            "INSERT INTO memory_organization_coverage VALUES (?,?,?,?,?,?,?)",
            [
                (
                    batch.community_id,
                    batch.character_id,
                    batch.batch_id,
                    stage,
                    source.kind,
                    source.source_id,
                    source.version,
                )
                for source in sources
            ],
        )

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
        for source in batch.sources:
            uncovered = connection.execute(
                "SELECT 1 FROM memory_segment_sources s WHERE s.segment_id=? AND NOT EXISTS "
                "(SELECT 1 FROM memory_organization_coverage c WHERE c.character_id=? "
                "AND c.stage='cognitions' AND c.source_kind=s.source_kind "
                "AND c.source_id=s.source_id AND c.source_version=s.source_version) LIMIT 1",
                (source.segment_id, batch.character_id),
            ).fetchone()
            if uncovered is None:
                connection.execute(
                    "INSERT INTO memory_organization_consumption VALUES (?,?,?,?,?)",
                    (source.segment_id, source.version, batch.batch_id, outcome, utc_text(now)),
                )
