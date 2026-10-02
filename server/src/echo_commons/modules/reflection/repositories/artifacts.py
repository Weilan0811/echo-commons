import json
import sqlite3
from uuid import UUID

from pydantic import TypeAdapter

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.reflection.contracts.candidates import ReflectionNodeAction
from echo_commons.modules.reflection.contracts.context import ArtifactInput
from echo_commons.modules.reflection.domain.graph import (
    ArtifactRef,
    EvidenceRef,
    OutputContractRef,
    ReflectionArtifact,
    register_artifact,
)
from echo_commons.shared.errors import NotFoundError

_ACTION = TypeAdapter(ReflectionNodeAction)


class ArtifactRepository:
    def audit(
        self, connection: sqlite3.Connection, graph_run_id: str, artifact_id: str
    ) -> dict[str, object]:
        row = connection.execute(
            "SELECT audit_json FROM reflection_artifacts "
            "WHERE graph_run_id = ? AND artifact_id = ?",
            (graph_run_id, artifact_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Reflection artifact does not exist in the graph scope")
        return json.loads(row[0])

    def get(
        self, connection: sqlite3.Connection, graph_run_id: str, artifact_id: str
    ) -> ReflectionArtifact:
        row = connection.execute(
            "SELECT * FROM reflection_artifacts WHERE graph_run_id = ? AND artifact_id = ?",
            (graph_run_id, artifact_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Reflection artifact does not exist in the graph scope")
        return ReflectionArtifact(
            artifact_id=UUID(row["artifact_id"]),
            graph_run_id=UUID(row["graph_run_id"]),
            node_task_id=UUID(row["node_task_id"]),
            attempt=row["attempt"],
            node_input_fingerprint=row["node_input_fingerprint"],
            output_contract=OutputContractRef(
                row["output_contract_kind"], row["output_contract_version"]
            ),
            payload=json.loads(row["payload_json"]),
            content_fingerprint=row["content_fingerprint"],
            evidence_refs=tuple(
                EvidenceRef(**item) for item in json.loads(row["evidence_refs_json"])
            ),
            created_at_utc=utc_datetime(row["created_at_utc"]),
            invocation_id=UUID(row["invocation_id"]) if row["invocation_id"] else None,
        )

    def inputs(
        self, connection: sqlite3.Connection, graph_run_id: str, refs: tuple[ArtifactRef, ...]
    ) -> tuple[ArtifactInput, ...]:
        result = []
        for ref in refs:
            artifact = self.get(connection, graph_run_id, str(ref.artifact_id))
            if artifact.content_fingerprint != ref.content_fingerprint:
                raise ValueError("Reflection artifact disagrees with its frozen input reference")
            node_key = connection.execute(
                "SELECT node_key FROM reflection_node_tasks WHERE node_task_id = ?",
                (str(artifact.node_task_id),),
            ).fetchone()[0]
            result.append(
                ArtifactInput(
                    artifact_id=str(artifact.artifact_id),
                    node_key=node_key,
                    content_version=str(artifact.content_fingerprint),
                    payload=_ACTION.validate_python(artifact.payload.to_dict()),
                )
            )
        return tuple(result)

    def add(
        self,
        connection: sqlite3.Connection,
        artifact: ReflectionArtifact,
        audit: dict[str, object],
    ) -> ReflectionArtifact:
        exists = connection.execute(
            "SELECT artifact_id FROM reflection_artifacts WHERE artifact_id = ?",
            (str(artifact.artifact_id),),
        ).fetchone()
        if exists is not None:
            return register_artifact(
                self.get(connection, str(artifact.graph_run_id), str(artifact.artifact_id)),
                artifact,
            )
        connection.execute(
            "INSERT INTO reflection_artifacts VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(artifact.artifact_id),
                str(artifact.graph_run_id),
                str(artifact.node_task_id),
                str(artifact.invocation_id) if artifact.invocation_id else None,
                artifact.attempt,
                str(artifact.node_input_fingerprint),
                artifact.output_contract.kind,
                artifact.output_contract.version,
                json.dumps(artifact.payload.to_dict(), ensure_ascii=False),
                str(artifact.content_fingerprint),
                json.dumps(
                    [
                        {"kind": item.kind, "ref": item.ref, "version": item.version}
                        for item in artifact.evidence_refs
                    ]
                ),
                json.dumps(audit, ensure_ascii=False),
                utc_text(artifact.created_at_utc),
            ),
        )
        return artifact
