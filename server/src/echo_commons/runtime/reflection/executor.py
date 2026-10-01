"""Execution of one claimed Reflection graph node."""

from __future__ import annotations

import asyncio
import json
from datetime import timedelta
from uuid import NAMESPACE_URL, UUID, uuid5

from pydantic import ValidationError

from echo_server.agents.contracts import (
    AgentInvocation,
    AgentRunResult,
    AgentRunStatus,
    ContextInputRef,
    Correlation,
    ExecutionPolicy,
    InvocationIdentity,
    InvocationPurpose,
    RecoveryAction,
    ReflectionNodeOutput,
    ReflectionNodeScope,
)
from echo_server.agents.contracts import EvidenceRef as ContractEvidenceRef
from echo_server.domain.errors import DomainInvariantError
from echo_server.domain.reflection_graph import (
    EvidenceRef,
    ReflectionArtifact,
    ReflectionExecutionKind,
    ReflectionGraphKind,
    ReflectionGraphRun,
    ReflectionGraphRunStatus,
)
from echo_server.domain.reflection_node import ReflectionNodeTask, ReflectionNodeTaskStatus
from echo_server.domain.reflection_result import GraphReviewRecord, GraphReviewStatus
from echo_server.observability.trace import safe_trace_payload
from echo_server.runtime.dispatcher.contracts import (
    TaskDisposition,
    TaskExecutionResult,
    TaskLease,
)
from echo_server.runtime.dispatcher.lease import LeaseHeartbeat
from echo_server.runtime.modules import ReflectionModule
from echo_server.runtime.recovery import decide_agent_run
from echo_server.runtime.reflection.batch import ReflectionBatch
from echo_server.runtime.reflection.coordinator import (
    ReflectionCoordinator,
    ReflectionGraphSnapshotStale,
    source_scopes_equal,
)
from echo_server.runtime.reflection.review import ChangeSetBuilder, ReflectionReviewer
from echo_server.services.model_gateway import resolve_agent_route
from echo_server.store.memory_provenance import MemoryProvenanceRepository


class ReflectionGraphExecutor:
    """Execute nodes and persist the graph aggregate after all required nodes."""

    task_kind = "reflection.graph.node"

    def __init__(self, runtime: ReflectionModule, coordinator: ReflectionCoordinator) -> None:
        self.runtime = runtime
        self.coordinator = coordinator
        self.reviewer = ReflectionReviewer(runtime.settings)
        self.change_set_builder = ChangeSetBuilder()

    async def execute(self, lease: TaskLease) -> TaskExecutionResult:
        task = lease.payload
        if not isinstance(task, ReflectionNodeTask):
            raise TypeError("reflection graph lease has an invalid payload")
        try:
            preparation = await self._prepare(task, lease)
        except ReflectionGraphSnapshotStale:
            return TaskExecutionResult(
                TaskDisposition.TERMINAL_FAILURE,
                "reflection_graph_snapshot_stale",
            )
        if isinstance(preparation, TaskExecutionResult):
            return preparation
        run, node, snapshot, node_input = preparation

        if node.execution_kind is ReflectionExecutionKind.MODEL:
            invocation = self._invocation(run, task, node_input, lease)
            if not self._has_model_material(run, snapshot):
                action = self._no_op_action("graph snapshot contains no source material")
                invocation_id = None
            else:
                run_result = await self._run_agent_with_lease(task, lease, invocation)
                action_result = _validate_node_run_result(run_result, invocation)
                await self.runtime.record_agent_run_observations(
                    invocation,
                    run_result,
                    entity_type="reflection_node_task",
                    entity_id=str(task.task_id),
                )
                if isinstance(action_result, TaskExecutionResult):
                    return action_result
                action = action_result
                invocation_id = invocation.identity.invocation_id
        elif node.execution_kind is ReflectionExecutionKind.RUNTIME:
            action = self._no_op_action("runtime policy node has no model action")
            invocation_id = None
        else:
            action = None
            invocation_id = None

        artifact = self._artifact(
            task,
            node.execution_kind,
            action,
            node_input,
            invocation_id=invocation_id,
            attempt=lease.attempt_count,
        )
        try:
            return await self._commit_node(
                task,
                lease,
                run,
                snapshot,
                node_input,
                artifact,
            )
        except ReflectionGraphSnapshotStale:
            return TaskExecutionResult(
                TaskDisposition.TERMINAL_FAILURE,
                "reflection_graph_snapshot_stale",
            )

    async def _prepare(
        self,
        task: ReflectionNodeTask,
        lease: TaskLease,
    ) -> tuple[ReflectionGraphRun, object, object, object] | TaskExecutionResult:
        now = self.runtime.clock()
        async with self.runtime.database.transaction() as connection:
            current = await self.runtime.reflection_graph_nodes.get(task.task_id, connection)
            if current is None:
                return TaskExecutionResult(TaskDisposition.STALE, "reflection_node_task_missing")
            if not current.has_valid_lease(
                worker_id=lease.lease_owner,
                now_utc=now,
                attempt_count=lease.attempt_count,
                lease_generation=lease.lease_generation,
            ):
                return TaskExecutionResult(TaskDisposition.STALE, "reflection_node_lease_invalid")
            run = await self.runtime.reflection_graph_runs.get(current.graph_run_id, connection)
            if run is None:
                return TaskExecutionResult(
                    TaskDisposition.TERMINAL_FAILURE,
                    "reflection_graph_missing",
                )
            if run.status is not ReflectionGraphRunStatus.RUNNING:
                return TaskExecutionResult(TaskDisposition.STALE, "reflection_graph_not_running")
            snapshot_build = await self.coordinator.load_snapshot(
                run,
                connection=connection,
            )
            definition = self.coordinator.definition_for(run)
            node = definition.node(current.node_key)
            predecessors = []
            for artifact_ref in current.input_artifact_refs:
                artifact = await self.runtime.reflection_graph_artifacts.get(
                    artifact_ref.artifact_id,
                    connection=connection,
                )
                if artifact is None or artifact.reference != artifact_ref:
                    raise ReflectionGraphSnapshotStale("predecessor Artifact is missing or changed")
                predecessors.append(artifact)
            node_input = self.coordinator.node_input_projector.project(
                snapshot_build.snapshot,
                node,
                predecessor_artifacts=tuple(predecessors),
                model_profile=self._model_profile(),
            )
            if node_input.node_input_fingerprint != current.node_input_fingerprint.value:
                raise ReflectionGraphSnapshotStale("node input fingerprint changed")
            return run, node, snapshot_build.snapshot, node_input

    async def _commit_node(
        self,
        task: ReflectionNodeTask,
        lease: TaskLease,
        run: ReflectionGraphRun,
        snapshot: object,
        node_input: object,
        artifact: ReflectionArtifact,
    ) -> TaskExecutionResult:
        now = self.runtime.clock()
        async with self.runtime.database.transaction(immediate=True) as connection:
            current = await self.runtime.reflection_graph_nodes.get(task.task_id, connection)
            current_run = await self.runtime.reflection_graph_runs.get(
                task.graph_run_id,
                connection,
            )
            if current is None or current_run is None:
                return TaskExecutionResult(TaskDisposition.STALE, "reflection_graph_state_missing")
            if current_run.status is not ReflectionGraphRunStatus.RUNNING:
                return TaskExecutionResult(TaskDisposition.STALE, "reflection_graph_not_running")
            if not current.has_valid_lease(
                worker_id=lease.lease_owner,
                now_utc=now,
                attempt_count=lease.attempt_count,
                lease_generation=lease.lease_generation,
            ):
                return TaskExecutionResult(TaskDisposition.STALE, "reflection_node_lease_invalid")
            actual = await self.coordinator.load_snapshot(
                current_run,
                connection=connection,
            )
            if (
                actual.snapshot.snapshot_id != snapshot.snapshot_id
                or actual.snapshot.snapshot_fingerprint != snapshot.snapshot_fingerprint
                or not source_scopes_equal(actual.source_scope, run.source_scope)
            ):
                return TaskExecutionResult(
                    TaskDisposition.TERMINAL_FAILURE,
                    "reflection_graph_snapshot_stale",
                )
            if current.node_input_fingerprint.value != node_input.node_input_fingerprint:
                return TaskExecutionResult(
                    TaskDisposition.TERMINAL_FAILURE,
                    "reflection_node_input_stale",
                )
            await self.runtime.reflection_graph_nodes.complete_with_artifact(
                current.task_id,
                artifact,
                worker_id=lease.lease_owner,
                now_utc=now,
                attempt_count=lease.attempt_count,
                lease_generation=lease.lease_generation,
                activate_successors=False,
                connection=connection,
            )
            updated_run, tasks = await self.coordinator.materialize_successors(
                current_run,
                actual.snapshot,
                now_utc=now,
                connection=connection,
            )
            await self._finish_if_ready(
                updated_run,
                tasks,
                actual.snapshot,
                now,
                connection,
            )
        return TaskExecutionResult(TaskDisposition.COMMITTED)

    async def _finish_if_ready(
        self,
        run: ReflectionGraphRun,
        tasks: tuple[ReflectionNodeTask, ...],
        snapshot: object,
        now: object,
        connection: object,
    ) -> None:
        definition = self.coordinator.definition_for(run)
        failed_tasks = tuple(
            task for task in tasks if task.status is ReflectionNodeTaskStatus.FAILED
        )
        required_failure = next(
            (task for task in failed_tasks if definition.node(task.node_key).required),
            None,
        )
        if required_failure is not None:
            failed_run = run.fail(
                now_utc=now,
                error_code=required_failure.last_error_code or "node_failed",
            )
            await self.runtime.reflection_graph_runs.save(
                failed_run,
                expected_updated_at_utc=run.updated_at_utc,
                connection=connection,
            )
            return
        partial_failures = tuple(
            {
                "node_key": task.node_key,
                "error_code": task.last_error_code or "node_failed",
                "attempt_count": task.attempt_count,
            }
            for task in failed_tasks
        )
        completed_keys = {
            task.node_key for task in tasks if task.status is ReflectionNodeTaskStatus.COMPLETED
        }
        skipped_keys = {
            task.node_key for task in tasks if task.status is ReflectionNodeTaskStatus.SKIPPED
        }
        if not definition.can_complete(
            completed_node_keys=completed_keys,
            skipped_node_keys=skipped_keys,
        ):
            return

        artifacts = await self.runtime.reflection_graph_artifacts.list_for_graph(
            run.graph_run_id,
            connection=connection,
        )
        aggregate_keys = {
            node.node_key
            for node in definition.nodes
            if node.execution_kind is ReflectionExecutionKind.AGGREGATE
        }
        aggregate_tasks = {task.task_id for task in tasks if task.node_key in aggregate_keys}
        model_tasks = tuple(task for task in tasks if task.task_id not in aggregate_tasks)
        model_artifacts = tuple(
            artifact for artifact in artifacts if artifact.node_task_id not in aggregate_tasks
        )
        batch = ReflectionBatch.from_artifacts(
            graph_run=run,
            node_tasks=model_tasks,
            artifacts=model_artifacts,
            snapshot=snapshot,
        )
        segment = None
        summary_batch = None
        if run.graph_kind is ReflectionGraphKind.SEGMENT_REFLECT:
            segment_source = next(
                (source for source in run.source_scope.sources if source.kind == "memory_segment"),
                None,
            )
            if segment_source is None:
                raise DomainInvariantError("reflection graph has no segment source")
            segment = await self.runtime.memory_segments.get(
                UUID(segment_source.ref),
                connection=connection,
            )
            if segment is None:
                raise DomainInvariantError("reflection_segment_not_found")
            reviewed = self.reviewer.review(
                batch.to_proposal_envelope(),
                batch=batch,
                graph_run=run,
                snapshot=snapshot,
                segment=segment,
            )
            if reviewed.approved:
                reviewed = self.change_set_builder.build(
                    reviewed,
                    segment_id=segment.segment_id,
                )
        elif run.graph_kind in {
            ReflectionGraphKind.MEMORY_ORGANIZE,
            ReflectionGraphKind.CONTINUITY_COMPRESS,
        }:
            batch_source = next(
                (
                    source
                    for source in run.source_scope.sources
                    if source.kind == "memory_summary_batch"
                ),
                None,
            )
            if batch_source is None:
                raise DomainInvariantError("reflection graph has no summary batch source")
            summary_batch = await MemoryProvenanceRepository().get_batch(
                batch_source.ref,
                account_id=run.account_id,
                character_id=run.character_id,
                connection=connection,
            )
            if summary_batch is None:
                raise DomainInvariantError(
                    "continuity_compression_batch_not_found"
                    if run.graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS
                    else "memory_organization_batch_not_found"
                )
            if run.graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
                reviewed = self.reviewer.review_continuity_compression(
                    batch.to_proposal_envelope(),
                    batch=batch,
                    graph_run=run,
                    snapshot=snapshot,
                    summary_batch=summary_batch,
                )
                if reviewed.approved:
                    reviewed = self.change_set_builder.build_continuity(
                        reviewed,
                        batch_id=summary_batch.batch_id,
                    )
            else:
                reviewed = self.reviewer.review_memory_organization(
                    batch.to_proposal_envelope(),
                    batch=batch,
                    graph_run=run,
                    snapshot=snapshot,
                    summary_batch=summary_batch,
                )
                if reviewed.approved:
                    reviewed = self.change_set_builder.build_memory(
                        reviewed,
                        batch_id=summary_batch.batch_id,
                    )
        else:
            raise DomainInvariantError("unsupported reflection graph kind")
        payload = batch.to_payload()
        if partial_failures:
            payload["partial_failures"] = list(partial_failures)
        aggregate_fingerprint = batch.aggregate_fingerprint.value
        result = GraphReviewRecord(
            result_id=uuid5(
                NAMESPACE_URL,
                f"reflection-graph-result:{run.graph_run_id}:{aggregate_fingerprint}",
            ),
            graph_run_id=run.graph_run_id,
            aggregate_fingerprint=aggregate_fingerprint,
            payload_json=json.dumps(payload, ensure_ascii=False, separators=(",", ":")),
            created_at_utc=now,
        )
        stored_result = await self.runtime.reflection_graph_results.ensure(
            result,
            connection=connection,
        )
        if stored_result.status is not GraphReviewStatus.PENDING:
            return
        if reviewed.approved:
            if run.graph_kind is ReflectionGraphKind.SEGMENT_REFLECT:
                await self.runtime.reflection_graph_commit.commit(
                    reviewed,
                    graph_run=run,
                    snapshot=snapshot,
                    segment=segment,
                    now=now,
                    connection=connection,
                )
            elif run.graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
                await self.runtime.reflection_graph_commit.commit_continuity_compression(
                    reviewed,
                    snapshot=snapshot,
                    summary_batch=summary_batch,
                    now=now,
                    connection=connection,
                )
            else:
                await self.runtime.reflection_graph_commit.commit_memory_organization(
                    reviewed,
                    graph_run=run,
                    snapshot=snapshot,
                    summary_batch=summary_batch,
                    now=now,
                    connection=connection,
                )
            decided = stored_result.decide(
                status=GraphReviewStatus.APPROVED,
                decided_at_utc=now,
                decision_code=reviewed.code.value,
            )
        else:
            decided = stored_result.decide(
                status=GraphReviewStatus.REJECTED,
                decided_at_utc=now,
                decision_code=reviewed.code.value,
            )
        await self.runtime.reflection_graph_results.save_decision(
            decided,
            connection=connection,
        )
        await self.runtime.task_traces.enqueue(
            trace_id=uuid5(
                NAMESPACE_URL,
                f"reflection-graph-reviewed:{run.graph_run_id}:{aggregate_fingerprint}",
            ),
            correlation_id=run.trace_id or run.graph_run_id,
            kind="reflection_graph.reviewed",
            entity_type="reflection_graph_run",
            entity_id=str(run.graph_run_id),
            payload=safe_trace_payload(
                "reflection_graph.reviewed",
                decision=decided.status.value,
                decision_code=decided.decision_code,
                artifact_count=len(payload["artifact_refs"]),
                partial=bool(partial_failures),
            ),
            created_at=now,
            connection=connection,
        )
        if reviewed.approved and reviewed.change_set is not None:
            change_set = reviewed.change_set
            if run.graph_kind is ReflectionGraphKind.SEGMENT_REFLECT:
                summary_count = int(change_set.summary is not None)
                relationship_count = len(change_set.relationship_impacts)
                state_count = len(change_set.state_entries)
                digest_count = 0
                memory_count = 0
                entity_count = 0
                edge_count = 0
            elif run.graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
                summary_count = 0
                relationship_count = 0
                state_count = 0
                digest_count = 1
                memory_count = 0
                entity_count = 0
                edge_count = 0
            else:
                summary_count = 0
                relationship_count = 0
                state_count = 0
                digest_count = 0
                memory_count = len(change_set.memory_entries)
                entity_count = len(change_set.entities)
                edge_count = len(change_set.edges)
            await self.runtime.task_traces.enqueue(
                trace_id=uuid5(
                    NAMESPACE_URL,
                    f"reflection-facts-committed:{run.graph_run_id}:{aggregate_fingerprint}",
                ),
                correlation_id=run.trace_id or run.graph_run_id,
                kind="reflection_facts.committed",
                entity_type="reflection_graph_run",
                entity_id=str(run.graph_run_id),
                payload=safe_trace_payload(
                    "reflection_facts.committed",
                    summary_count=summary_count,
                    relationship_count=relationship_count,
                    state_count=state_count,
                    digest_count=digest_count,
                    memory_count=memory_count,
                    entity_count=entity_count,
                    edge_count=edge_count,
                    fact_count=(
                        summary_count
                        + digest_count
                        + relationship_count
                        + state_count
                        + memory_count
                        + entity_count
                        + edge_count
                    ),
                ),
                created_at=now,
                connection=connection,
            )
        if partial_failures:
            final_run = run.partial(
                now_utc=now,
                completed_node_keys=completed_keys,
                failed_node_keys=tuple(item["node_key"] for item in partial_failures),
                skipped_node_keys=skipped_keys,
            )
            trace_kind = "reflection_graph.partial"
            trace_id = uuid5(NAMESPACE_URL, f"reflection-graph-partial:{run.graph_run_id}")
        else:
            final_run = run.complete(
                now_utc=now,
                completed_node_keys=completed_keys,
                skipped_node_keys=skipped_keys,
            )
            trace_kind = "reflection_graph.completed"
            trace_id = uuid5(NAMESPACE_URL, f"reflection-graph-completed:{run.graph_run_id}")
        await self.runtime.reflection_graph_runs.save(
            final_run,
            expected_updated_at_utc=run.updated_at_utc,
            connection=connection,
        )
        await self.runtime.task_traces.enqueue(
            trace_id=trace_id,
            correlation_id=run.trace_id or run.graph_run_id,
            kind=trace_kind,
            entity_type="reflection_graph_run",
            entity_id=str(run.graph_run_id),
            payload=safe_trace_payload(
                trace_kind,
                outcome=payload["outcome"],
                artifact_count=len(payload["artifact_refs"]),
                aggregate_fingerprint=aggregate_fingerprint,
                decision=decided.status.value,
                decision_code=decided.decision_code,
                partial=bool(partial_failures),
            ),
            created_at=now,
            connection=connection,
        )

    async def _run_agent_with_lease(
        self,
        task: ReflectionNodeTask,
        lease: TaskLease,
        invocation: AgentInvocation,
    ) -> AgentRunResult:
        agent_task = asyncio.create_task(
            self.runtime.agent.run(invocation),
            name=f"echo-reflection-graph-agent-{task.task_id}",
        )

        async def renew() -> object | None:
            return await self.runtime.reflection_graph_nodes.renew_lease(
                task.task_id,
                worker_id=lease.lease_owner,
                now_utc=self.runtime.clock(),
                lease_seconds=self.runtime.settings.lease_seconds,
                attempt_count=lease.attempt_count,
                lease_generation=lease.lease_generation,
            )

        heartbeat_task = asyncio.create_task(
            LeaseHeartbeat(
                renew,
                interval_seconds=self.runtime.settings.lease_heartbeat_interval_seconds,
            ).run(),
            name=f"echo-reflection-graph-heartbeat-{task.task_id}",
        )
        try:
            done, _ = await asyncio.wait(
                (agent_task, heartbeat_task),
                return_when=asyncio.FIRST_COMPLETED,
            )
            if heartbeat_task in done:
                await heartbeat_task
            return await agent_task
        finally:
            if not heartbeat_task.done():
                heartbeat_task.cancel()
            if not agent_task.done():
                agent_task.cancel()
            await asyncio.gather(heartbeat_task, agent_task, return_exceptions=True)

    def _invocation(
        self,
        run: ReflectionGraphRun,
        task: ReflectionNodeTask,
        node_input: object,
        lease: TaskLease,
    ) -> AgentInvocation:
        return AgentInvocation(
            identity=InvocationIdentity(
                agent_id=self.runtime.agent.agent_id,
                agent_kind=self.runtime.agent.agent_kind,
                purpose=InvocationPurpose.REFLECTION,
                attempt=lease.attempt_count,
            ),
            scope=ReflectionNodeScope(
                graph_run_id=run.graph_run_id,
                node_task_id=task.task_id,
                node_key=task.node_key,
                character_id=run.character_id,
            ),
            context=node_input,
            context_input=ContextInputRef(
                snapshot_id=node_input.snapshot_ref.snapshot_id,
                snapshot_schema_version=node_input.snapshot_ref.snapshot_schema_version,
                snapshot_fingerprint=node_input.snapshot_ref.snapshot_fingerprint,
            ),
            output_contract=node_input.output_contract,
            execution_policy=ExecutionPolicy(
                allowed_tools=(),
                model_profile=node_input.model_profile,
                harness_version=self.runtime.agent.harness_version,
                max_model_steps=self.runtime.settings.reflection_max_model_steps,
                max_model_requests=self.runtime.settings.reflection_max_model_requests,
                max_tool_calls=0,
                max_output_tokens=self.runtime.settings.reflection_max_output_tokens,
                temperature=self.runtime.settings.reflection_temperature,
                top_p=self.runtime.settings.reflection_top_p,
                deadline_utc=lease.lease_until_utc
                - timedelta(seconds=max(0.0, self.runtime.settings.lease_safety_margin_seconds)),
            ),
            correlation=Correlation(
                task_id=task.task_id,
                trace_id=run.trace_id
                or uuid5(NAMESPACE_URL, f"reflection-graph:{run.graph_run_id}"),
            ),
        )

    @staticmethod
    def _has_model_material(run: ReflectionGraphRun, snapshot: object) -> bool:
        if run.graph_kind in {
            ReflectionGraphKind.MEMORY_ORGANIZE,
            ReflectionGraphKind.CONTINUITY_COMPRESS,
        }:
            return bool(getattr(snapshot, "materials", ()))
        return bool(getattr(snapshot, "has_window_material", False))

    @staticmethod
    def _no_op_action(reason: str) -> object:
        from echo_server.agents.contracts import NoOpReflectionAction

        return NoOpReflectionAction(reason=reason)

    def _artifact(
        self,
        task: ReflectionNodeTask,
        execution_kind: ReflectionExecutionKind,
        action: object | None,
        node_input: object,
        *,
        invocation_id: UUID | None,
        attempt: int,
    ) -> ReflectionArtifact:
        if execution_kind is ReflectionExecutionKind.AGGREGATE:
            payload = {
                "kind": "reflection_aggregate",
                "node_key": task.node_key,
                "artifact_refs": [
                    {
                        "artifact_id": str(ref.artifact_id),
                        "content_fingerprint": ref.content_fingerprint.value,
                    }
                    for ref in task.input_artifact_refs
                ],
            }
            evidence_refs = tuple(
                EvidenceRef(
                    kind="artifact",
                    ref=f"artifact:{ref.artifact_id}",
                    version=ref.content_fingerprint.value,
                )
                for ref in task.input_artifact_refs
            )
        else:
            if action is None:
                raise DomainInvariantError("non-aggregate graph node has no action")
            payload = action.model_dump(mode="json")
            evidence_refs = tuple(_domain_evidence(ref) for ref in node_input.evidence_refs)
        return ReflectionArtifact.create(
            artifact_id=uuid5(
                NAMESPACE_URL,
                f"reflection-node-artifact:{task.task_id}:{attempt}:{node_input.node_input_fingerprint}",
            ),
            graph_run_id=task.graph_run_id,
            node_task_id=task.task_id,
            attempt=attempt,
            node_input_fingerprint=task.node_input_fingerprint,
            output_contract=task.output_contract,
            payload=payload,
            evidence_refs=evidence_refs,
            created_at_utc=self.runtime.clock(),
            invocation_id=invocation_id,
        )

    def _model_profile(self) -> str:
        return resolve_agent_route(self.runtime.agent, "character.reflection").resolved_profile


def _domain_evidence(ref: ContractEvidenceRef) -> EvidenceRef:
    return EvidenceRef(kind=ref.kind, ref=ref.ref, version=ref.version)


def _validate_node_run_result(
    raw: object,
    invocation: AgentInvocation,
) -> object | TaskExecutionResult:
    if isinstance(raw, AgentRunResult):
        result = raw
    else:
        try:
            result = AgentRunResult.model_validate(raw)
        except ValidationError as exc:
            raise ValueError("reflection graph Agent Run result is invalid") from exc
    if result.invocation_id != invocation.identity.invocation_id:
        raise ValueError("reflection graph Agent Run returned a different invocation")
    if (
        result.agent_id != invocation.identity.agent_id
        or result.agent_kind != invocation.identity.agent_kind
    ):
        raise ValueError("reflection graph Agent Run returned a different agent")
    if result.status not in {AgentRunStatus.COMPLETED, AgentRunStatus.NO_PROPOSAL}:
        decision = decide_agent_run(result)
        if decision is None:
            raise ValueError("reflection graph Agent Run has no recovery decision")
        disposition = (
            TaskDisposition.RETRY
            if decision.action is RecoveryAction.RETRY_TASK
            else TaskDisposition.TERMINAL_FAILURE
        )
        return TaskExecutionResult(disposition, decision.failure.code)
    if result.status is AgentRunStatus.NO_PROPOSAL:
        return _no_op_result("Agent returned no proposal")
    if result.status is not AgentRunStatus.COMPLETED:
        raise ValueError("reflection graph Agent Run did not complete")
    if not isinstance(result.output, ReflectionNodeOutput):
        raise ValueError("reflection graph Agent Run did not return a node output")
    if result.output.contract.schema_id != invocation.output_contract.schema_id:
        raise ValueError("reflection graph Agent Run returned a different output contract")
    return result.output.action


def _no_op_result(reason: str) -> object:
    from echo_server.agents.contracts import NoOpReflectionAction

    return NoOpReflectionAction(reason=reason)


__all__ = ["ReflectionGraphExecutor"]
