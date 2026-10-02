import sqlite3
from datetime import datetime

from echo_commons.modules.reflection.domain.graph import content_fingerprint
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.input import prepare_node_input


def bind_ready_inputs(
    connection: sqlite3.Connection,
    graph_run_id: str,
    now: datetime,
    runs: RunRepository,
    nodes: NodeRepository,
    artifacts: ArtifactRepository,
) -> None:
    scope = runs.scope(connection, graph_run_id)
    snapshot = runs.snapshot(connection, scope.community_id, scope.character_id, graph_run_id)
    graph_nodes = nodes.for_graph(connection, graph_run_id)
    by_key = {node.node_key: node for node in graph_nodes}
    for node in graph_nodes:
        if node.status != "pending" or not node.activated or not node.dependency_keys:
            continue
        predecessors = tuple(by_key[key] for key in node.dependency_keys)
        if any(not item.is_terminal for item in predecessors):
            continue
        refs = tuple(
            artifacts.get(connection, graph_run_id, str(item.artifact_id)).reference
            for item in predecessors
            if item.status == "completed"
        )
        context = prepare_node_input(
            snapshot,
            graph_run_id=graph_run_id,
            node_task_id=str(node.task_id),
            node_key=node.node_key,
            node_kind=node.node_kind,
            artifacts=artifacts.inputs(connection, graph_run_id, refs),
        )
        nodes.save(
            connection,
            node.bind_input_artifacts(
                input_artifact_refs=refs,
                node_input_fingerprint=content_fingerprint(context.model_dump(mode="json")),
                now_utc=now,
            ),
        )
