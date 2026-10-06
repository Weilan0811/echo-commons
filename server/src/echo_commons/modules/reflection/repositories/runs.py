import json
import sqlite3
from dataclasses import asdict
from uuid import UUID

from echo_commons.agents.contracts.input import ActorScope
from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot
from echo_commons.modules.reflection.domain.graph import (
    GraphSourceRef,
    ReflectionGraphKind,
    ReflectionGraphRun,
    ReflectionSourceScope,
    content_fingerprint,
)
from echo_commons.shared.errors import NotFoundError


def source_scope_fingerprint(scope: ReflectionSourceScope) -> str:
    return str(content_fingerprint({"sources": [asdict(source) for source in scope.sources]}))


class RunRepository:
    def blocks_consumer(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
        kind: ReflectionGraphKind,
    ) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM reflection_graph_runs WHERE community_id=? AND character_id=? "
                "AND graph_kind=? AND json_extract(snapshot_json,'$.conversation_id')=? "
                "AND status IN ('pending','running','retry_wait','partial','failed') LIMIT 1",
                (community_id, character_id, kind.value, conversation_id),
            ).fetchone()
            is not None
        )

    def scope(self, connection: sqlite3.Connection, graph_run_id: str) -> ActorScope:
        row = connection.execute(
            "SELECT community_id, character_id FROM reflection_graph_runs WHERE graph_run_id = ?",
            (graph_run_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("Reflection graph does not exist")
        return ActorScope(community_id=row["community_id"], character_id=row["character_id"])

    def _map(self, row: sqlite3.Row) -> ReflectionGraphRun:
        return ReflectionGraphRun(
            graph_run_id=UUID(row["graph_run_id"]),
            graph_kind=row["graph_kind"],
            graph_version=row["graph_version"],
            community_id=row["community_id"],
            character_id=row["character_id"],
            context_snapshot_id=row["context_snapshot_id"],
            snapshot_fingerprint=row["snapshot_fingerprint"],
            source_scope=ReflectionSourceScope(
                tuple(GraphSourceRef(**source) for source in json.loads(row["source_scope_json"]))
            ),
            topology_node_keys=tuple(json.loads(row["topology_node_keys_json"])),
            required_node_keys=tuple(json.loads(row["required_node_keys_json"])),
            registered_node_keys=tuple(json.loads(row["registered_node_keys_json"])),
            status=row["status"],
            execution_generation=row["execution_generation"],
            created_at_utc=utc_datetime(row["created_at_utc"]),
            updated_at_utc=utc_datetime(row["updated_at_utc"]),
            started_at_utc=utc_datetime(row["started_at_utc"]) if row["started_at_utc"] else None,
            completed_at_utc=utc_datetime(row["completed_at_utc"])
            if row["completed_at_utc"]
            else None,
            last_error_code=row["last_error_code"],
            trace_id=UUID(row["trace_id"]) if row["trace_id"] else None,
        )

    def get(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        graph_run_id: str,
    ) -> ReflectionGraphRun:
        row = connection.execute(
            "SELECT * FROM reflection_graph_runs WHERE community_id = ? AND character_id = ? "
            "AND graph_run_id = ?",
            (community_id, character_id, graph_run_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Reflection run does not exist in the character scope")
        return self._map(row)

    def find_source(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        kind: ReflectionGraphKind,
        scope: ReflectionSourceScope,
    ) -> ReflectionGraphRun | None:
        row = connection.execute(
            "SELECT * FROM reflection_graph_runs WHERE community_id = ? AND character_id = ? "
            "AND graph_kind = ? AND graph_version = 'v1' AND source_scope_fingerprint = ? "
            "ORDER BY created_at_utc LIMIT 1",
            (community_id, character_id, kind.value, source_scope_fingerprint(scope)),
        ).fetchone()
        return self._map(row) if row else None

    def snapshot(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        graph_run_id: str,
    ) -> GraphContextSnapshot:
        self.get(connection, community_id, character_id, graph_run_id)
        row = connection.execute(
            "SELECT snapshot_json FROM reflection_graph_runs WHERE graph_run_id = ?",
            (graph_run_id,),
        ).fetchone()
        return GraphContextSnapshot.model_validate_json(row[0])

    def add(
        self,
        connection: sqlite3.Connection,
        run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
    ) -> None:
        connection.execute(
            "INSERT INTO reflection_graph_runs "
            "(graph_run_id, community_id, character_id, graph_kind, graph_version, "
            "context_snapshot_id, "
            "snapshot_schema_version, snapshot_json, snapshot_fingerprint, source_scope_json, "
            "source_scope_fingerprint, topology_node_keys_json, required_node_keys_json, "
            "registered_node_keys_json, status, execution_generation, "
            "created_at_utc, updated_at_utc, "
            "started_at_utc, completed_at_utc, last_error_code, trace_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(run.graph_run_id),
                run.community_id,
                run.character_id,
                run.graph_kind.value,
                run.graph_version,
                run.context_snapshot_id,
                snapshot.schema_version,
                snapshot.model_dump_json(),
                str(run.snapshot_fingerprint),
                json.dumps([asdict(source) for source in run.source_scope.sources]),
                source_scope_fingerprint(run.source_scope),
                json.dumps(run.topology_node_keys),
                json.dumps(run.required_node_keys),
                json.dumps(run.registered_node_keys),
                run.status.value,
                run.execution_generation,
                utc_text(run.created_at_utc),
                utc_text(run.updated_at_utc),
                utc_text(run.started_at_utc) if run.started_at_utc else None,
                utc_text(run.completed_at_utc) if run.completed_at_utc else None,
                run.last_error_code,
                str(run.trace_id) if run.trace_id else None,
            ),
        )

    def save(self, connection: sqlite3.Connection, run: ReflectionGraphRun) -> None:
        connection.execute(
            "UPDATE reflection_graph_runs SET registered_node_keys_json = ?, status = ?, "
            "execution_generation = ?, updated_at_utc = ?, "
            "started_at_utc = ?, completed_at_utc = ?, "
            "last_error_code = ? WHERE graph_run_id = ? AND community_id = ? AND character_id = ?",
            (
                json.dumps(run.registered_node_keys),
                run.status.value,
                run.execution_generation,
                utc_text(run.updated_at_utc),
                utc_text(run.started_at_utc) if run.started_at_utc else None,
                utc_text(run.completed_at_utc) if run.completed_at_utc else None,
                run.last_error_code,
                str(run.graph_run_id),
                run.community_id,
                run.character_id,
            ),
        )
