from datetime import datetime
from uuid import uuid4

from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.run import AgentRunResult
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import Disposition, ExecutionOutcome, TaskLease
from echo_commons.execution.errors import ExecutionDeferred
from echo_commons.execution.lease import LeaseLostError
from echo_commons.execution.observations import ExecutionEventPayload
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.observability.outbox import enqueue_trace
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.reflection.contexts.sources import ReflectionSources
from echo_commons.modules.reflection.contracts.candidates import (
    FactReviewModelAction,
    MemoryCognitionReflectAction,
    NoOpReflectionAction,
    SegmentSummaryAction,
)
from echo_commons.modules.reflection.domain.graph import (
    EvidenceRef,
    ReflectionArtifact,
)
from echo_commons.modules.reflection.policy import allows_follow_up
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.dependencies import bind_ready_inputs
from echo_commons.modules.reflection.tasks.diagnosis import CandidateDiagnosis
from echo_commons.modules.reflection.tasks.projection import NodeReferences, project_node_input
from echo_commons.modules.reflection.tasks.queue import ReflectionQueue
from echo_commons.modules.reflection.tasks.review import ReflectionReview, bind_fact_review


class ReflectionNodeCommit:
    def __init__(
        self,
        database: Database,
        queue: ReflectionQueue,
        artifacts: ArtifactRepository,
        contexts: ReflectionSources,
        review: ReflectionReview,
        diagnosis: CandidateDiagnosis | None = None,
    ) -> None:
        self.database, self.queue, self.artifacts = database, queue, artifacts
        self.nodes: NodeRepository = queue.nodes
        self.runs: RunRepository = queue.runs
        self.contexts, self.review = contexts, review
        self.diagnosis = diagnosis

    def commit(
        self,
        lease: TaskLease,
        invocation: AgentInvocation,
        result: AgentRunResult,
        now: datetime,
    ) -> ReflectionArtifact | ExecutionOutcome:
        with self.database.transaction() as connection:
            now = utc_now()
            node = self.nodes.get(connection, lease.task_id)
            run = self.queue.run_for(connection, node)
            if node.status == "completed" and node.attempt_count == lease.attempt:
                artifact = self.artifacts.get(
                    connection, str(run.graph_run_id), str(node.artifact_id)
                )
                if artifact.invocation_id == invocation.identity.invocation_id:
                    return artifact
            if run.is_terminal or not self.queue.owned(connection, lease, now):
                raise LeaseLostError("Reflection node lease is no longer current")
            if not self.queue.available(connection, run):
                raise ExecutionDeferred()
            if self.diagnosis is not None and not self.diagnosis.approved(
                connection, lease, invocation, result
            ):
                self.queue.recovery.reject(
                    connection, lease, "reflection_diagnosis_required", invocation, result, now
                )
                return ExecutionOutcome(Disposition.HANDLED)
            action = result.output.payload if result.output is not None else None
            if isinstance(action, FactReviewModelAction):
                try:
                    action = bind_fact_review(invocation.context, action)
                except (KeyError, ValueError, StopIteration):
                    self.queue.recovery.reject(
                        connection,
                        lease,
                        "reflection_fact_decision_invalid",
                        invocation,
                        result,
                        now,
                    )
                    return ExecutionOutcome(Disposition.HANDLED)
            if invocation.output_contract.version in ("v5", "v3", "v6") and action is not None:
                try:
                    action = NodeReferences.from_input(invocation.context).bind(action)
                except (KeyError, ValueError):
                    self.queue.recovery.reject(
                        connection,
                        lease,
                        "reflection_record_reference_unknown",
                        invocation,
                        result,
                        now,
                    )
                    return ExecutionOutcome(Disposition.HANDLED)
            error = self.review.check(lease, node, invocation, result, action)
            if error is not None:
                self.queue.recovery.reject(connection, lease, error, invocation, result, now)
                return ExecutionOutcome(Disposition.HANDLED)
            context = invocation.context
            self.contexts.check_sources(connection, context.graph_snapshot)
            if not action.evidence_refs and not isinstance(
                action, (NoOpReflectionAction, MemoryCognitionReflectAction)
            ):
                action = action.model_copy(
                    update={"evidence_refs": project_node_input(context).evidence_refs}
                )
            versions = {
                material.evidence_ref: material.version
                for material in context.graph_snapshot.materials
            }
            versions.update(
                {f"artifact:{item.artifact_id}": item.content_version for item in context.artifacts}
            )
            evidence = tuple(
                EvidenceRef(*reference.split(":", 1), version=versions[reference])
                for reference in action.evidence_refs
            )
            artifact = ReflectionArtifact.create(
                artifact_id=uuid4(),
                graph_run_id=node.graph_run_id,
                node_task_id=node.task_id,
                attempt=lease.attempt,
                node_input_fingerprint=node.node_input_fingerprint,
                output_contract=node.output_contract,
                payload=action.model_dump(mode="json"),
                evidence_refs=evidence,
                created_at_utc=now,
                invocation_id=invocation.identity.invocation_id,
            )
            self.artifacts.add(
                connection,
                artifact,
                {"model_profile": result.model_profile, "usage": result.usage_summary.model_dump()},
            )
            completed = node.complete(
                worker_id=lease.owner,
                now_utc=now,
                artifact=artifact,
                attempt_count=lease.attempt,
                lease_generation=lease.generation,
            )
            self.nodes.save(connection, completed)
            if node.node_key == "segment_summary_plan":
                selected = set()
                if isinstance(action, SegmentSummaryAction):
                    if action.follow_up.relationship_reflect:
                        selected.add("relationship_reflect")
                    if action.follow_up.state_reflect:
                        selected.add("state_reflect")
                instance = InstanceRepository().get(connection, run.community_id, run.character_id)
                if not allows_follow_up(instance):
                    selected.clear()
                for successor in self.nodes.for_graph(connection, str(run.graph_run_id)):
                    if successor.node_key in ("relationship_reflect", "state_reflect"):
                        successor = (
                            successor.activate(now_utc=now)
                            if successor.node_key in selected
                            else successor.skip(now_utc=now, reason_code="follow_up_not_requested")
                        )
                        self.nodes.save(connection, successor)
            bind_ready_inputs(
                connection, str(run.graph_run_id), now, self.runs, self.nodes, self.artifacts
            )
            enqueue_trace(
                connection,
                str(uuid4()),
                lease.trace_id,
                "reflection.node.completed",
                "reflection_node",
                lease.task_id,
                {"attempt": lease.attempt, "artifact_id": str(artifact.artifact_id)},
                now,
            )
            self.queue.recorder.record(
                connection,
                lease,
                "completed",
                ExecutionEventPayload(observation=self.queue.recorder.observation(result)),
                now,
                str(result.invocation_id),
            )
            return artifact
