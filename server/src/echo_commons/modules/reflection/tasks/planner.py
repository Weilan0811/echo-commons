from uuid import uuid4

from echo_commons.agents.contracts.run import UsageSummary
from echo_commons.execution.lease import LeaseLostError
from echo_commons.execution.observations import ExecutionEventPayload, ExecutionObservation
from echo_commons.modules.reflection.contracts.candidates import NoOpReflectionAction
from echo_commons.modules.reflection.domain.graph import (
    ReflectionArtifact,
    reflection_graph_definition,
)
from echo_commons.modules.reflection.tasks.dependencies import bind_ready_inputs


def plan_views(queue, lease, now):
    with queue.database.transaction() as connection:
        node = queue.nodes.get(connection, lease.task_id)
        run = queue.run_for(connection, node)
        if not queue.owned(connection, lease, now):
            raise LeaseLostError("View planner lease expired")
        snapshot = queue.runs.snapshot(
            connection, run.community_id, run.character_id, str(run.graph_run_id)
        )
        kinds = {item.fact_kind for item in snapshot.materials}
        definition = reflection_graph_definition(run.graph_kind, version=run.graph_version)
        branches = tuple(item for item in definition.nodes if item.fact_kind is not None)
        selected = {item.node_key for item in branches if item.fact_kind in kinds}
        artifact = ReflectionArtifact.create(
            artifact_id=uuid4(),
            graph_run_id=run.graph_run_id,
            node_task_id=node.task_id,
            attempt=lease.attempt,
            node_input_fingerprint=node.node_input_fingerprint,
            output_contract=node.output_contract,
            payload=NoOpReflectionAction(
                kind="no_op", reason="按正式变化选择认识刷新分支。"
            ).model_dump(mode="json"),
            evidence_refs=(),
            created_at_utc=now,
        )
        queue.artifacts.add(connection, artifact, {"selected_nodes": sorted(selected)})
        queue.nodes.save(
            connection,
            node.complete(
                worker_id=lease.owner,
                now_utc=now,
                artifact=artifact,
                attempt_count=lease.attempt,
                lease_generation=lease.generation,
            ),
        )
        for successor in queue.nodes.for_graph(connection, str(run.graph_run_id)):
            if successor.node_key in {item.node_key for item in branches}:
                queue.nodes.save(
                    connection,
                    successor.activate(now_utc=now)
                    if successor.node_key in selected
                    else successor.skip(now_utc=now, reason_code="unchanged_fact_kind"),
                )
        bind_ready_inputs(
            connection, str(run.graph_run_id), now, queue.runs, queue.nodes, queue.artifacts
        )
        queue.recorder.record(
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
