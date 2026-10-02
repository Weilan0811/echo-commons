import sqlite3

from echo_commons.infrastructure.observability.query import read_traces
from echo_commons.modules.memory.domain.organization import normalize_alias
from echo_commons.modules.reflection.contracts.candidates import (
    MemoryEdgeCandidate,
    MemoryEntityCandidate,
    ReflectionBatchProposal,
)
from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind


class ReflectionDiagnosticsRepository:
    def facts(
        self,
        connection: sqlite3.Connection,
        snapshot: GraphContextSnapshot,
        approved_payload: dict[str, object] | None,
    ) -> tuple[dict[str, object], ...]:
        community, character = snapshot.scope.community_id, snapshot.scope.character_id
        source = snapshot.source_id
        facts = []
        if snapshot.source_kind == "memory_segment":
            rows = connection.execute(
                "SELECT segment_id, summary_text, summary_version, status FROM memory_segments "
                "WHERE community_id = ? AND character_id = ? AND segment_id = ? "
                "AND status = 'ingested' AND summary_text IS NOT NULL",
                (community, character, source),
            )
            facts.extend({"fact_kind": "segment_summary", **dict(row)} for row in rows)
            for table, kind, owner in (
                ("character_state_entries", "character_state", "character_id"),
                ("relation_evidence", "relation_evidence", "observer_character_id"),
            ):
                rows = connection.execute(
                    f"SELECT * FROM {table} WHERE community_id = ? AND {owner} = ? "
                    "AND source_kind = ? AND source_ref = ?",
                    (community, character, snapshot.source_kind, source),
                )
                facts.extend({"fact_kind": kind, **dict(row)} for row in rows)
        elif snapshot.graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
            rows = connection.execute(
                "SELECT * FROM conversation_digests WHERE batch_id = ?", (source,)
            )
            facts.extend({"fact_kind": "conversation_digest", **dict(row)} for row in rows)
        elif snapshot.graph_kind is ReflectionGraphKind.MEMORY_ORGANIZE:
            rows = connection.execute(
                "SELECT * FROM memory_entries WHERE community_id = ? AND character_id = ? "
                "AND source_kind = 'memory_summary_batch' AND source_ref = ?",
                (community, character, source),
            )
            facts.extend({"fact_kind": "memory_entry", **dict(row)} for row in rows)
            rows = connection.execute(
                "SELECT * FROM memory_organization_consumption WHERE batch_id = ?", (source,)
            )
            facts.extend({"fact_kind": "summary_consumption", **dict(row)} for row in rows)
            if approved_payload is not None:
                candidates = ReflectionBatchProposal.model_validate(
                    approved_payload["proposal"]
                ).candidates
                entities = {}
                for candidate in candidates:
                    if not isinstance(candidate, MemoryEntityCandidate):
                        continue
                    row = connection.execute(
                        "SELECT e.* FROM memory_entities e JOIN memory_entity_aliases a "
                        "ON a.entity_id = e.entity_id AND a.character_id = e.character_id "
                        "WHERE e.community_id = ? AND e.character_id = ? "
                        "AND a.normalized_alias = ? AND a.invalidated_at_utc IS NULL",
                        (community, character, normalize_alias(candidate.canonical_name)),
                    ).fetchone()
                    if row is not None:
                        entities[candidate.entity_id] = row["entity_id"]
                        facts.append({"fact_kind": "memory_entity", **dict(row)})
                for candidate in candidates:
                    if not isinstance(candidate, MemoryEdgeCandidate):
                        continue
                    row = connection.execute(
                        "SELECT * FROM memory_edges WHERE character_id = ? "
                        "AND from_entity_id = ? AND to_entity_id = ? AND edge_kind = ? "
                        "AND source_memory_id IS NULL AND invalidated_at_utc IS NULL",
                        (
                            character,
                            entities[candidate.from_entity_id],
                            entities[candidate.to_entity_id],
                            candidate.edge_kind,
                        ),
                    ).fetchone()
                    if row is not None:
                        facts.append({"fact_kind": "memory_edge", **dict(row)})
        return tuple(facts)

    def traces(
        self, connection: sqlite3.Connection, trace_id: str
    ) -> tuple[dict[str, object], ...]:
        return read_traces(connection, trace_id)
