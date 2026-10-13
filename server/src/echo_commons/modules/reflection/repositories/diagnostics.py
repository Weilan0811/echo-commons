import sqlite3

from echo_commons.infrastructure.observability.query import read_traces
from echo_commons.modules.reflection.domain.graph import ReflectionGraphKind


class ReflectionDiagnosticsRepository:
    def facts(
        self,
        connection: sqlite3.Connection,
        run,
        snapshot: dict,
    ) -> tuple[dict[str, object], ...]:
        community, character = run.community_id, run.character_id
        source = snapshot["source_id"]
        facts = []
        if snapshot["source_kind"] == "memory_segment":
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
                    (community, character, snapshot["source_kind"], source),
                )
                facts.extend({"fact_kind": kind, **dict(row)} for row in rows)
        elif run.graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
            rows = connection.execute(
                "SELECT * FROM conversation_digests WHERE batch_id = ?", (source,)
            )
            facts.extend({"fact_kind": "conversation_digest", **dict(row)} for row in rows)
        elif run.graph_kind is ReflectionGraphKind.MEMORY_ORGANIZE:
            for kind, table in (
                ("memory_fact", "memory_facts"),
                ("memory_cognition", "memory_cognitions"),
            ):
                rows = connection.execute(
                    f"SELECT * FROM {table} WHERE community_id=? AND character_id=? "
                    f"AND source_ref=?",
                    (community, character, source),
                )
                facts.extend({"fact_kind": kind, **dict(row)} for row in rows)
            rows = connection.execute(
                "SELECT * FROM memory_organization_stages WHERE character_id=? AND batch_id=?",
                (character, source),
            )
            facts.extend({"fact_kind": "organization_stage", **dict(row)} for row in rows)
            rows = connection.execute(
                "SELECT * FROM memory_organization_consumption WHERE batch_id = ?", (source,)
            )
            facts.extend({"fact_kind": "summary_consumption", **dict(row)} for row in rows)
            if snapshot["source_kind"] == "author_material_batch":
                rows = connection.execute(
                    "SELECT * FROM memory_author_batches WHERE batch_id=? "
                    "AND consumed_at_utc IS NOT NULL",
                    (source,),
                )
                facts.extend({"fact_kind": "author_consumption", **dict(row)} for row in rows)
        elif run.graph_kind is ReflectionGraphKind.VIEW_REFRESH:
            rows = connection.execute(
                "SELECT * FROM memory_views WHERE community_id=? "
                "AND character_id=? AND source_snapshot_version=?",
                (community, character, snapshot["source_version"]),
            )
            facts.extend({"fact_kind": "memory_view", **dict(row)} for row in rows)
            row = connection.execute(
                "SELECT * FROM memory_change_batches WHERE batch_id=? "
                "AND consumed_at_utc IS NOT NULL",
                (source,),
            ).fetchone()
            if row:
                facts.append({"fact_kind": "view_consumption", **dict(row)})
        return tuple(facts)

    def traces(
        self, connection: sqlite3.Connection, trace_id: str
    ) -> tuple[dict[str, object], ...]:
        return read_traces(connection, trace_id)
