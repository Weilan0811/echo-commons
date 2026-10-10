import json
import sqlite3
from datetime import datetime
from uuid import uuid4

from pydantic import ValidationError

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.recovery import FailureCategory
from echo_commons.agents.contracts.run import UsageSummary
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.errors import ExecutionDeferred
from echo_commons.execution.lease import LeaseLostError
from echo_commons.execution.observations import ExecutionEventPayload, ExecutionObservation
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.observability.outbox import enqueue_trace
from echo_commons.modules.memory.domain.views import ViewBranchResult
from echo_commons.modules.memory.repositories.changes import MemoryChangeRepository
from echo_commons.modules.reflection.contexts.sources import (
    ReflectionSources,
    ReflectionSourceUnavailable,
)
from echo_commons.modules.reflection.domain.graph import (
    EvidenceRef,
    ReflectionArtifact,
    ReflectionExecutionKind,
    ReflectionGraphRun,
    content_fingerprint,
)
from echo_commons.modules.reflection.domain.node import ReflectionNodeTask
from echo_commons.modules.reflection.domain.result import GraphReviewRecord, GraphReviewStatus
from echo_commons.modules.reflection.registry import ReflectionGraphRegistry
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.results import ResultRepository
from echo_commons.modules.reflection.tasks.aggregate import aggregate_artifacts
from echo_commons.modules.reflection.tasks.facts import ReflectionFacts
from echo_commons.modules.reflection.tasks.graph_review import GraphReview
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.queue import ReflectionQueue
from echo_commons.shared.errors import BusinessError


class ReflectionGraphCommit:
    def __init__(
        self,
        database: Database,
        queue: ReflectionQueue,
        artifacts: ArtifactRepository,
        results: ResultRepository,
        registry: ReflectionGraphRegistry,
        contexts: ReflectionSources,
        review: GraphReview,
        facts: ReflectionFacts,
    ) -> None:
        self.database, self.queue, self.artifacts, self.results = (
            database,
            queue,
            artifacts,
            results,
        )
        self.registry, self.contexts, self.review = registry, contexts, review
        self.facts = facts

    def commit(self, lease: TaskLease, now: datetime) -> GraphReviewRecord:
        with self.database.transaction() as connection:
            now = utc_now()
            node = self.queue.nodes.get(connection, lease.task_id)
            run = self.queue.run_for(connection, node)
            definition = self.registry.require(run.graph_kind, run.graph_version)
            if (
                definition.node(node.node_key).execution_kind
                is not ReflectionExecutionKind.AGGREGATE
            ):
                raise ValueError("Graph commit requires the fixed aggregate node")
            existing = self.results.for_graph(connection, str(run.graph_run_id))
            if existing is not None:
                if node.attempt_count != lease.attempt or lease.trace_id != str(run.trace_id):
                    raise LeaseLostError("Aggregate result belongs to another execution")
                return existing
            if run.is_terminal or not self.queue.owned(connection, lease, now):
                raise LeaseLostError("Aggregate lease is no longer current")
            if not self.queue.available(connection, run):
                raise ExecutionDeferred()
            scope = self.queue.runs.scope(connection, str(run.graph_run_id))
            snapshot = self.queue.runs.snapshot(
                connection, scope.community_id, scope.character_id, str(run.graph_run_id)
            )
            inputs = self.artifacts.inputs(
                connection, str(run.graph_run_id), node.input_artifact_refs
            )
            context = prepare_node_input(
                snapshot,
                graph_run_id=str(run.graph_run_id),
                node_task_id=str(node.task_id),
                node_key=node.node_key,
                node_kind=node.node_kind,
                artifacts=inputs,
            )
            if content_fingerprint(context.model_dump(mode="json")) != node.node_input_fingerprint:
                raise ExecutionError("reflection_input_mismatch", FailureCategory.SOURCE)
            graph_nodes = self.queue.nodes.for_graph(connection, str(run.graph_run_id))
            if any(not item.is_terminal for item in graph_nodes if item.task_id != node.task_id):
                raise ValueError("Graph aggregate requires all other nodes to finish")
            artifacts = tuple(
                self.artifacts.get(connection, str(run.graph_run_id), str(item.artifact_id))
                for item in graph_nodes
                if item.status == "completed"
            )
            supplement = connection.execute(
                "SELECT node_keys_json FROM reflection_supplements WHERE graph_run_id=?",
                (str(run.graph_run_id),),
            ).fetchone()
            if supplement:
                requested = set(json.loads(supplement[0]))
                ids = {item.artifact_id for item in graph_nodes if item.node_key in requested}
                artifacts = tuple(item for item in artifacts if item.artifact_id in ids)
            payload = {
                "artifact_refs": [
                    {
                        "artifact_id": str(artifact.artifact_id),
                        "version": str(artifact.content_fingerprint),
                    }
                    for artifact in artifacts
                ]
            }
            try:
                self.contexts.check_sources(connection, snapshot)
                batch = aggregate_artifacts(
                    snapshot,
                    artifacts,
                    max_candidates=(
                        self.review.budget.limits(snapshot)[0]
                        if self.review.budget
                        else self.review.max_candidates
                    ),
                )
            except (BusinessError, ReflectionSourceUnavailable, ValidationError) as error:
                code = (
                    error.code
                    if isinstance(error, (BusinessError, ReflectionSourceUnavailable))
                    else "reflection_batch_invalid"
                )
                return self._reject(connection, lease, node, run, payload, code, now)
            payload["proposal"] = batch.compact_dump()
            count_limit, char_limit = (
                self.review.budget.limits(snapshot)
                if self.review.budget
                else (self.review.max_candidates, self.review.max_output_chars)
            )
            payload["budget"] = dict(
                candidate_count=len(batch.candidates),
                candidate_limit=count_limit,
                content_chars=batch.content_chars,
                content_char_limit=char_limit,
                source_count=len({ref for item in batch.candidates for ref in item.source_refs}),
            )
            error_code = self.review.check(snapshot, batch, supplement=supplement is not None)
            if error_code is not None:
                return self._reject(connection, lease, node, run, payload, error_code, now)
            # 业务校验失败时撤销事实写入，仍然保存图级审核决定。
            connection.execute("SAVEPOINT reflection_facts")
            view_kinds = {
                item.task_id: definition.node(item.node_key).view_kind
                for item in graph_nodes
                if definition.node(item.node_key).view_kind is not None
            }
            try:
                self.facts.apply(
                    connection,
                    snapshot,
                    batch,
                    now,
                    supplement=supplement is not None,
                    view_results=tuple(
                        ViewBranchResult(
                            view_kinds[artifact.node_task_id],
                            "no_op" if artifact.payload.get("kind") == "no_op" else "completed",
                        )
                        for artifact in artifacts
                        if artifact.node_task_id in view_kinds
                    ),
                )
            except BusinessError as error:
                connection.execute("ROLLBACK TO SAVEPOINT reflection_facts")
                connection.execute("RELEASE SAVEPOINT reflection_facts")
                return self._reject(connection, lease, node, run, payload, error.code, now)
            connection.execute("RELEASE SAVEPOINT reflection_facts")
            result = self._record(run, payload, GraphReviewStatus.APPROVED, "approved", now)
            self.results.add(connection, result)
            evidence = tuple(
                EvidenceRef(material.kind, material.source_id, material.version)
                for material in snapshot.materials
            )
            artifact = ReflectionArtifact.create(
                artifact_id=uuid4(),
                graph_run_id=run.graph_run_id,
                node_task_id=node.task_id,
                attempt=lease.attempt,
                node_input_fingerprint=node.node_input_fingerprint,
                output_contract=node.output_contract,
                payload=batch.compact_dump(),
                evidence_refs=evidence,
                created_at_utc=now,
            )
            self.artifacts.add(connection, artifact, {"result_id": str(result.result_id)})
            completed = node.complete(
                worker_id=lease.owner,
                now_utc=now,
                artifact=artifact,
                attempt_count=lease.attempt,
                lease_generation=lease.generation,
            )
            self.queue.nodes.save(connection, completed)
            completed_keys = {
                item.node_key for item in graph_nodes if item.status == "completed"
            } | {node.node_key}
            skipped_keys = {item.node_key for item in graph_nodes if item.status == "skipped"}
            failed_keys = {item.node_key for item in graph_nodes if item.status == "failed"}
            run = (
                run.partial(
                    now_utc=now,
                    completed_node_keys=completed_keys,
                    skipped_node_keys=skipped_keys,
                    failed_node_keys=failed_keys,
                )
                if failed_keys
                else run.complete(
                    now_utc=now, completed_node_keys=completed_keys, skipped_node_keys=skipped_keys
                )
            )
            self.queue.runs.save(connection, run)
            enqueue_trace(
                connection,
                str(uuid4()),
                lease.trace_id,
                "reflection.graph.approved",
                "reflection_graph",
                str(run.graph_run_id),
                {"result_id": str(result.result_id), "status": run.status.value},
                now,
            )
            self.queue.recorder.record(
                connection,
                lease,
                "completed",
                ExecutionEventPayload(
                    observation=ExecutionObservation(
                        provider_attempt_count=0, usage_summary=UsageSummary()
                    )
                ),
                now,
            )
            return result

    def _record(
        self,
        run: ReflectionGraphRun,
        payload: dict[str, object],
        status: GraphReviewStatus,
        code: str,
        now: datetime,
    ) -> GraphReviewRecord:
        return GraphReviewRecord(
            uuid4(),
            run.graph_run_id,
            str(content_fingerprint(payload)),
            json.dumps(payload, ensure_ascii=False),
            now,
        ).decide(status=status, decided_at_utc=now, decision_code=code)

    def _reject(
        self,
        connection: sqlite3.Connection,
        lease: TaskLease,
        node: ReflectionNodeTask,
        run: ReflectionGraphRun,
        payload: dict[str, object],
        code: str,
        now: datetime,
    ) -> GraphReviewRecord:
        if code == "reflection_source_unavailable":
            snapshot = self.queue.runs.snapshot(
                connection, run.community_id, run.character_id, str(run.graph_run_id)
            )
            if snapshot.source_kind == "memory_change_set":
                MemoryChangeRepository().supersede(connection, snapshot, now)
        status = (
            GraphReviewStatus.EXPIRED
            if code == "reflection_source_unavailable"
            else GraphReviewStatus.REJECTED
        )
        result = self._record(run, payload, status, code, now)
        self.results.add(connection, result)
        self.queue.recovery.apply(
            connection, lease, self.queue.recovery.review(code, repairable=False), now
        )
        enqueue_trace(
            connection,
            str(uuid4()),
            lease.trace_id,
            "reflection.graph.rejected",
            "reflection_graph",
            str(run.graph_run_id),
            {"result_id": str(result.result_id), "decision_code": code},
            now,
        )
        return result
