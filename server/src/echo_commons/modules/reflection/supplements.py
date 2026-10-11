import json
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.reflection.domain.graph import ReflectionArtifact, ReflectionGraphKind
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.tasks.dependencies import bind_ready_inputs
from echo_commons.shared.errors import ConflictError


def supplement(coordinator, connection, original, now):
    if original.graph_kind not in {
        ReflectionGraphKind.SEGMENT_REFLECT,
        ReflectionGraphKind.VIEW_REFRESH,
    }:
        raise ConflictError("This graph requires atomic recovery")
    child = connection.execute(
        "SELECT r.graph_run_id FROM reflection_supplements s "
        "JOIN reflection_graph_runs r USING(graph_run_id) WHERE s.original_run_id=? "
        "ORDER BY s.created_at_utc DESC LIMIT 1",
        (str(original.graph_run_id),),
    ).fetchone()
    if child:
        return coordinator.runs.get(
            connection, original.community_id, original.character_id, child[0]
        )
    previous = coordinator.nodes.for_graph(connection, str(original.graph_run_id))
    failed = {node.node_key for node in previous if node.status == "failed"}
    if not failed:
        raise ConflictError("Partial graph has no failed branches")
    snapshot = coordinator.runs.snapshot(
        connection, original.community_id, original.character_id, str(original.graph_run_id)
    )
    coordinator.context.sources.check_sources(connection, snapshot)
    run = coordinator.start_snapshot_in(connection, snapshot, now)
    connection.execute(
        "INSERT INTO reflection_supplements VALUES (?,?,?,?)",
        (
            str(run.graph_run_id),
            str(original.graph_run_id),
            json.dumps(sorted(failed)),
            utc_text(now),
        ),
    )
    connection.execute(
        "UPDATE memory_relationship_refreshes SET graph_run_id=? WHERE graph_run_id=?",
        (str(run.graph_run_id), str(original.graph_run_id)),
    )
    repository = ArtifactRepository()
    definition = coordinator.registry.require(run.graph_kind)
    by_key = {node.node_key: node for node in previous}
    for node in coordinator.nodes.for_graph(connection, str(run.graph_run_id)):
        if node.node_key == definition.aggregate_node_key:
            continue
        if node.node_key in failed:
            coordinator.nodes.save(
                connection, node.activate(now_utc=now) if not node.activated else node
            )
        elif by_key[node.node_key].status == "completed":
            old = repository.get(
                connection, str(original.graph_run_id), str(by_key[node.node_key].artifact_id)
            )
            artifact = ReflectionArtifact.create(
                artifact_id=uuid4(),
                graph_run_id=run.graph_run_id,
                node_task_id=node.task_id,
                attempt=old.attempt,
                node_input_fingerprint=node.node_input_fingerprint,
                output_contract=node.output_contract,
                payload=old.payload.to_dict(),
                evidence_refs=old.evidence_refs,
                created_at_utc=now,
            )
            repository.add(
                connection,
                artifact,
                {
                    "reused_artifact_id": str(old.artifact_id),
                    "original_run_id": str(original.graph_run_id),
                },
            )
            coordinator.nodes.save(connection, node.reuse_completed(artifact, now_utc=now))
        else:
            coordinator.nodes.save(
                connection, node.skip(now_utc=now, reason_code="original_branch_skipped")
            )
    bind_ready_inputs(
        connection, str(run.graph_run_id), now, coordinator.runs, coordinator.nodes, repository
    )
    return run
