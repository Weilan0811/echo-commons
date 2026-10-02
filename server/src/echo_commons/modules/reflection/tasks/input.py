from echo_commons.agents.contracts.input import SourceVersion
from echo_commons.modules.reflection.contracts.context import (
    ArtifactInput,
    GraphContextSnapshot,
    ReflectionNodeInput,
)
from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind


def prepare_node_input(
    snapshot: GraphContextSnapshot,
    *,
    graph_run_id: str,
    node_task_id: str,
    node_key: str,
    node_kind: ReflectionNodeKind,
    artifacts: tuple[ArtifactInput, ...] = (),
) -> ReflectionNodeInput:
    return ReflectionNodeInput(
        snapshot_id=f"{snapshot.snapshot_id}/{node_task_id}",
        prepared_at_utc=snapshot.prepared_at_utc,
        scope=snapshot.scope,
        action_space=snapshot.action_space,
        source_versions=(
            *snapshot.source_versions,
            *(
                SourceVersion(
                    kind="reflection_artifact",
                    source_id=artifact.artifact_id,
                    version=artifact.content_version,
                )
                for artifact in artifacts
            ),
        ),
        graph_run_id=graph_run_id,
        node_key=node_key,
        node_kind=node_kind,
        graph_snapshot=snapshot,
        artifacts=artifacts,
    )
