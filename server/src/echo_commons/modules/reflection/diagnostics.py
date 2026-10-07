import json
from dataclasses import asdict

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.execution_records import ExecutionRecordRepository
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.reflection.domain.graph import content_fingerprint
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.diagnostics import ReflectionDiagnosticsRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.results import ResultRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.inspection import redact_thoughts
from echo_commons.shared.management import PageOptions, read_page


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
            snapshot_payload = redact_thoughts(
                connection,
                community_id,
                character_id,
                snapshot.model_dump(mode="json"),
            )
            decision = asdict(result) if result else None
            if decision is not None:
                decision["proposal"] = json.loads(decision.pop("payload_json"))
            return {
                "schema_version": 1,
                "supplement": next(
                    (
                        dict(
                            original_run_id=row["original_run_id"],
                            retry_node_keys=json.loads(row["node_keys_json"]),
                        )
                        for row in connection.execute(
                            "SELECT * FROM reflection_supplements WHERE graph_run_id=?",
                            (graph_run_id,),
                        )
                    ),
                    None,
                ),
                "supplement_run_ids": tuple(
                    row[0]
                    for row in connection.execute(
                        "SELECT graph_run_id FROM reflection_supplements WHERE original_run_id=? "
                        "ORDER BY created_at_utc",
                        (graph_run_id,),
                    )
                ),
                "recovery_summary": self._summary(
                    connection, graph_run_id, run.status, run.execution_generation
                ),
                "node_recovery": {
                    str(node.task_id): ExecutionRecordRepository().summary(
                        connection,
                        "reflection",
                        str(node.task_id),
                        node.status,
                        run.execution_generation,
                    )
                    for node in nodes
                },
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

    def list(
        self,
        community_id: str,
        character_id: str,
        options: PageOptions,
        *,
        status: str | None = None,
    ) -> dict:
        with self.database.read() as connection:
            InstanceRepository().get(connection, community_id, character_id)
            sql = (
                "SELECT graph_run_id,community_id,character_id,graph_kind,graph_version,status,"
                "execution_generation,last_error_code,trace_id,created_at_utc,updated_at_utc,"
                "started_at_utc,completed_at_utc FROM reflection_graph_runs "
                "WHERE community_id = ? AND character_id = ?"
            )
            parameters = (community_id, character_id)
            if status is not None:
                sql += " AND status = ?"
                parameters = (*parameters, status)
            page = read_page(
                connection,
                sql,
                parameters,
                scope={
                    "query": "reflection_runs",
                    "community_id": community_id,
                    "character_id": character_id,
                    "status": status,
                },
                order=("created_at_utc", "graph_run_id"),
                options=options,
            )

            for item in page["items"]:
                item.update(
                    self._summary(
                        connection,
                        item["graph_run_id"],
                        item["status"],
                        item["execution_generation"],
                    )
                )
            return page

    def _summary(self, connection, graph_run_id, state, generation):
        row = connection.execute(
            (
                "SELECT task_id FROM task_execution_events WHERE graph_run_id=? "
                "AND graph_execution_generation=? AND event_kind='recovery_applied' "
                "ORDER BY event_id DESC LIMIT 1"
            ),
            (graph_run_id, generation),
        ).fetchone()
        return ExecutionRecordRepository().summary(
            connection, "reflection", row[0] if row else "", state, generation
        )

    def node_input(
        self,
        community_id: str,
        character_id: str,
        graph_run_id: str,
        node_task_id: str,
        options: PageOptions | None = None,
    ) -> dict:
        with self.database.read() as connection:
            self.runs.get(connection, community_id, character_id, graph_run_id)
            node = self.nodes.get(connection, node_task_id)
            if str(node.graph_run_id) != graph_run_id:
                raise NotFoundError("Node does not belong to this reflection graph")
            snapshot = self.runs.snapshot(connection, community_id, character_id, graph_run_id)
            inputs = self.artifacts.inputs(connection, graph_run_id, node.input_artifact_refs)
            context = prepare_node_input(
                snapshot,
                graph_run_id=graph_run_id,
                node_task_id=node_task_id,
                node_key=node.node_key,
                node_kind=node.node_kind,
                artifacts=inputs,
            )
            predecessors = {
                item.node_key: item for item in self.nodes.for_graph(connection, graph_run_id)
            }
            ready = (
                node.activated
                and node.status != "skipped"
                and all(predecessors[key].is_terminal for key in node.dependency_keys)
                and content_fingerprint(context.model_dump(mode="json"))
                == node.node_input_fingerprint
            )
            payload = context.model_dump(mode="json") if ready else None
            if payload is not None:
                redact_thoughts(connection, community_id, character_id, payload["graph_snapshot"])
            return {
                "community_id": community_id,
                "character_id": character_id,
                "graph_run_id": graph_run_id,
                "node_task_id": node_task_id,
                "recovery_history": ExecutionRecordRepository().history(
                    connection,
                    "reflection",
                    node_task_id,
                    community_id,
                    character_id,
                    options or PageOptions(),
                    graph_run_id,
                ),
                "input_ready": ready,
                "input": payload,
            }

    def scheduling_result(self, run, *, restarted: bool = False) -> dict:
        with self.database.read() as connection:
            snapshot = self.runs.snapshot(
                connection,
                run.community_id,
                run.character_id,
                str(run.graph_run_id),
            )
            summary = asdict(run)
            summary["graph_run_id"] = str(run.graph_run_id)
            summary["trace_id"] = str(run.trace_id) if run.trace_id else None
            return {
                "outcome": "restarted"
                if restarted
                else ("existing" if run.is_terminal else "scheduled"),
                "graph_run": summary,
                "source_kind": snapshot.source_kind,
                "source_id": snapshot.source_id,
            }
