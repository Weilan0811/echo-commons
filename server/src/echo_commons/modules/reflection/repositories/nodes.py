import json
import sqlite3
from uuid import UUID

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.reflection.domain.graph import (
    ArtifactRef,
    OutputContractRef,
    ReflectionLease,
)
from echo_commons.modules.reflection.domain.node import ReflectionNodeTask
from echo_commons.shared.errors import NotFoundError


class NodeRepository:
    def _map(self, row: sqlite3.Row) -> ReflectionNodeTask:
        return ReflectionNodeTask(
            task_id=UUID(row["node_task_id"]),
            graph_run_id=UUID(row["graph_run_id"]),
            node_key=row["node_key"],
            node_kind=row["node_kind"],
            dependency_keys=tuple(json.loads(row["dependency_keys_json"])),
            activated=bool(row["activated"]),
            node_input_fingerprint=row["node_input_fingerprint"],
            input_artifact_refs=tuple(
                ArtifactRef(UUID(ref["artifact_id"]), ref["content_fingerprint"])
                for ref in json.loads(row["input_artifact_refs_json"])
            ),
            output_contract=OutputContractRef(
                row["output_contract_kind"], row["output_contract_version"]
            ),
            status=row["status"],
            attempt_count=row["attempt_count"],
            lease_generation=row["lease_generation"],
            lease=ReflectionLease(
                row["lease_owner"],
                row["attempt_count"],
                row["lease_generation"],
                utc_datetime(row["lease_until_utc"]),
            )
            if row["lease_owner"]
            else None,
            artifact_id=UUID(row["artifact_id"]) if row["artifact_id"] else None,
            available_at_utc=utc_datetime(row["available_at_utc"]),
            created_at_utc=utc_datetime(row["created_at_utc"]),
            updated_at_utc=utc_datetime(row["updated_at_utc"]),
            last_error_code=row["last_error_code"],
        )

    def get(self, connection: sqlite3.Connection, node_task_id: str) -> ReflectionNodeTask:
        row = connection.execute(
            "SELECT n.*, a.artifact_id FROM reflection_node_tasks n "
            "LEFT JOIN reflection_artifacts a "
            "ON a.node_task_id = n.node_task_id AND (a.attempt = n.attempt_count "
            "OR (n.status='completed' AND n.attempt_count=0 "
            "AND json_extract(a.audit_json,'$.reused_artifact_id') IS NOT NULL)) "
            "WHERE n.node_task_id = ?",
            (node_task_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("Reflection node does not exist")
        return self._map(row)

    def for_graph(
        self, connection: sqlite3.Connection, graph_run_id: str
    ) -> tuple[ReflectionNodeTask, ...]:
        return tuple(
            self.get(connection, row[0])
            for row in connection.execute(
                "SELECT node_task_id FROM reflection_node_tasks WHERE graph_run_id = ? "
                "ORDER BY created_at_utc, node_key",
                (graph_run_id,),
            )
        )

    def add(self, connection: sqlite3.Connection, node: ReflectionNodeTask) -> None:
        connection.execute(
            "INSERT INTO reflection_node_tasks "
            "(node_task_id, graph_run_id, node_key, node_kind, dependency_keys_json, activated, "
            "node_input_fingerprint, input_artifact_refs_json, output_contract_kind, "
            "output_contract_version, status, available_at_utc, created_at_utc, updated_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, '[]', ?, ?, 'pending', ?, ?, ?)",
            (
                str(node.task_id),
                str(node.graph_run_id),
                node.node_key,
                node.node_kind.value,
                json.dumps(node.dependency_keys),
                int(node.activated),
                str(node.node_input_fingerprint),
                node.output_contract.kind,
                node.output_contract.version,
                utc_text(node.available_at_utc),
                utc_text(node.created_at_utc),
                utc_text(node.updated_at_utc),
            ),
        )

    def save(self, connection: sqlite3.Connection, node: ReflectionNodeTask) -> None:
        refs = [
            {
                "artifact_id": str(ref.artifact_id),
                "content_fingerprint": str(ref.content_fingerprint),
            }
            for ref in node.input_artifact_refs
        ]
        connection.execute(
            "UPDATE reflection_node_tasks SET activated = ?, node_input_fingerprint = ?, "
            "input_artifact_refs_json = ?, status = ?, attempt_count = ?, lease_generation = ?, "
            "available_at_utc = ?, lease_owner = ?, lease_until_utc = ?, last_error_code = ?, "
            "updated_at_utc = ? WHERE node_task_id = ? AND graph_run_id = ?",
            (
                int(node.activated),
                str(node.node_input_fingerprint),
                json.dumps(refs),
                node.status.value,
                node.attempt_count,
                node.lease_generation,
                utc_text(node.available_at_utc),
                node.lease_owner,
                utc_text(node.lease_until_utc) if node.lease_until_utc else None,
                node.last_error_code,
                utc_text(node.updated_at_utc),
                str(node.task_id),
                str(node.graph_run_id),
            ),
        )
