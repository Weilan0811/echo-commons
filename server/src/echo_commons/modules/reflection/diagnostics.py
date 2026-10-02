import json
from dataclasses import asdict

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.diagnostics import ReflectionDiagnosticsRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.results import ResultRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository


class ReflectionRunView:
    def __init__(
        self,
        database: Database,
        runs: RunRepository,
        nodes: NodeRepository,
        artifacts: ArtifactRepository,
        results: ResultRepository,
        diagnostics: ReflectionDiagnosticsRepository,
    ) -> None:
        self.database, self.runs, self.nodes = database, runs, nodes
        self.artifacts, self.results, self.diagnostics = artifacts, results, diagnostics

    def get(self, community_id: str, character_id: str, graph_run_id: str) -> dict[str, object]:
        with self.database.read() as connection:
            run = self.runs.get(connection, community_id, character_id, graph_run_id)
            snapshot = self.runs.snapshot(connection, community_id, character_id, graph_run_id)
            nodes = self.nodes.for_graph(connection, graph_run_id)
            artifacts = tuple(
                self.artifacts.get(connection, graph_run_id, str(node.artifact_id))
                for node in nodes
                if node.artifact_id is not None
            )
            result = self.results.for_graph(connection, graph_run_id)
            snapshot_payload = snapshot.model_dump(mode="json")
            for material in snapshot_payload["materials"]:
                if material["kind"] != "thought":
                    continue
                row = connection.execute(
                    "SELECT content_removed_at_utc FROM thoughts WHERE community_id = ? "
                    "AND character_id = ? AND thought_id = ?",
                    (community_id, character_id, material["source_id"]),
                ).fetchone()
                if row is not None and row[0] is not None:
                    material["content"] = None
                    material["content_removed_at_utc"] = row[0]
            decision = asdict(result) if result else None
            if decision is not None:
                decision["proposal"] = json.loads(decision.pop("payload_json"))
            return {
                "schema_version": 1,
                "graph_run": asdict(run),
                "node_tasks": tuple(asdict(node) for node in nodes),
                "snapshot": snapshot_payload,
                "artifacts": tuple(
                    {
                        "artifact_id": str(artifact.artifact_id),
                        "node_task_id": str(artifact.node_task_id),
                        "attempt": artifact.attempt,
                        "output_contract": asdict(artifact.output_contract),
                        "content_version": str(artifact.content_fingerprint),
                        "payload": artifact.payload.to_dict(),
                        "audit": self.artifacts.audit(
                            connection, graph_run_id, str(artifact.artifact_id)
                        ),
                        "evidence_refs": tuple(asdict(ref) for ref in artifact.evidence_refs),
                    }
                    for artifact in artifacts
                ),
                "result": decision,
                "facts": self.diagnostics.facts(
                    connection,
                    snapshot,
                    json.loads(result.payload_json)
                    if result and result.status == "approved"
                    else None,
                ),
                "traces": self.diagnostics.traces(connection, str(run.trace_id)),
            }
