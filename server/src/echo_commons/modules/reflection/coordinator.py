import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from echo_commons.execution.records import ExecutionRecorder
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.observability.outbox import enqueue_trace
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.reflection.contexts.segment import SegmentContext
from echo_commons.modules.reflection.contexts.summaries import SummaryContext
from echo_commons.modules.reflection.contracts.context import GraphContextSnapshot
from echo_commons.modules.reflection.domain.graph import (
    GraphSourceRef,
    ReflectionGraphKind,
    ReflectionGraphRun,
    ReflectionSourceScope,
    content_fingerprint,
)
from echo_commons.modules.reflection.domain.node import ReflectionNodeTask
from echo_commons.modules.reflection.policy import require_graph
from echo_commons.modules.reflection.registry import ReflectionGraphRegistry
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.results import ResultRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.dependencies import bind_ready_inputs
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.shared.errors import ConflictError


class ReflectionCoordinator:
    def __init__(
        self,
        database: Database,
        registry: ReflectionGraphRegistry,
        segments: SegmentRepository,
        context: SegmentContext,
        runs: RunRepository,
        nodes: NodeRepository,
        summaries: SummaryContext,
        recorder: ExecutionRecorder,
    ) -> None:
        self.database, self.registry, self.segments = database, registry, segments
        self.context, self.runs, self.nodes = context, runs, nodes
        self.summaries = summaries
        self.recorder = recorder

    def start_segment(
        self,
        community_id: str,
        character_id: str,
        segment_id: str,
    ) -> ReflectionGraphRun:
        with self.database.transaction() as connection:
            return self.start_segment_in(connection, community_id, character_id, segment_id)

    def start_segment_in(
        self,
        connection,
        community_id: str,
        character_id: str,
        segment_id: str,
    ) -> ReflectionGraphRun:
        now = datetime.now(UTC)
        segment = self.segments.get(connection, community_id, character_id, segment_id)
        scope = ReflectionSourceScope(
            (
                GraphSourceRef("memory_segment", segment.segment_id, segment.source_version),
                *(
                    GraphSourceRef(source.kind.value, source.source_id, source.version)
                    for source in segment.sources
                ),
            )
        )
        kind = ReflectionGraphKind.SEGMENT_REFLECT
        existing = self.runs.find_source(connection, community_id, character_id, kind, scope)
        if existing is not None:
            return self._resume(connection, existing, now)
        snapshot = self.context.prepare(connection, community_id, character_id, segment_id, now)
        return self._create(connection, snapshot, scope, now)

    def start_summary(
        self,
        community_id: str,
        character_id: str,
        batch_id: str,
        graph_kind: ReflectionGraphKind,
    ) -> ReflectionGraphRun:
        with self.database.transaction() as connection:
            return self.start_summary_in(
                connection, community_id, character_id, batch_id, graph_kind
            )

    def start_summary_in(
        self,
        connection,
        community_id: str,
        character_id: str,
        batch_id: str,
        graph_kind: ReflectionGraphKind,
    ) -> ReflectionGraphRun:
        now = datetime.now(UTC)
        snapshot = self.summaries.prepare(
            connection, community_id, character_id, batch_id, graph_kind, now
        )
        scope = ReflectionSourceScope(
            (
                GraphSourceRef(snapshot.source_kind, batch_id, snapshot.source_version),
                *(
                    GraphSourceRef(material.kind, material.source_id, material.version)
                    for material in snapshot.materials
                ),
            )
        )
        existing = self.runs.find_source(connection, community_id, character_id, graph_kind, scope)
        if existing is not None:
            return self._resume(connection, existing, now)
        return self._create(connection, snapshot, scope, now)

    def restart(
        self, community_id: str, character_id: str, graph_run_id: str
    ) -> ReflectionGraphRun:
        with self.database.transaction() as connection:
            run = self.runs.get(connection, community_id, character_id, graph_run_id)
            if run.status != "failed" or ResultRepository().for_graph(connection, graph_run_id):
                raise ConflictError(
                    "Only failed reflection graphs without final review can restart"
                )
            return self._resume(connection, run, datetime.now(UTC))

    def _resume(
        self, connection: sqlite3.Connection, run: ReflectionGraphRun, now: datetime
    ) -> ReflectionGraphRun:
        graph_id = str(run.graph_run_id)
        if run.status != "failed" or ResultRepository().for_graph(connection, graph_id):
            return run
        snapshot = self.runs.snapshot(connection, run.community_id, run.character_id, graph_id)
        self.context.sources.check_sources(connection, snapshot)
        artifacts = ArtifactRepository()
        definition = self.registry.require(run.graph_kind, run.graph_version)
        selected = set()
        graph_nodes = self.nodes.for_graph(connection, graph_id)
        for node in graph_nodes:
            if node.node_key == "segment_summary_plan" and node.status == "completed":
                plan = artifacts.get(connection, graph_id, str(node.artifact_id)).payload.to_dict()
                selected.update(
                    key for key, requested in plan.get("follow_up", {}).items() if requested
                )
        for node in graph_nodes:
            if node.status == "failed" or (
                node.status == "skipped" and node.last_error_code == "required_node_failed"
            ):
                self.nodes.save(
                    connection,
                    node.reactivate(
                        now_utc=now, activated=definition.is_activated(node.node_key, selected)
                    ),
                )
        resumed = run.reactivate(now_utc=now)
        self.runs.save(connection, resumed)
        for node in self.nodes.for_graph(connection, graph_id):
            if node.status == "pending":
                self.recorder.node_transition(connection, node, resumed, "graph_restarted", now)
        bind_ready_inputs(connection, graph_id, now, self.runs, self.nodes, artifacts)
        enqueue_trace(
            connection,
            str(uuid4()),
            str(run.trace_id),
            "reflection.graph.restarted",
            "reflection_graph",
            graph_id,
            {"execution_generation": run.execution_generation},
            now,
        )
        return resumed

    def _create(
        self,
        connection: sqlite3.Connection,
        snapshot: GraphContextSnapshot,
        scope: ReflectionSourceScope,
        now: datetime,
    ) -> ReflectionGraphRun:
        definition = self.registry.require(snapshot.graph_kind)
        require_graph(
            InstanceRepository().get(
                connection, snapshot.scope.community_id, snapshot.scope.character_id
            ),
            snapshot.graph_kind,
        )
        run = ReflectionGraphRun.create(
            graph_run_id=uuid4(),
            definition=definition,
            community_id=snapshot.scope.community_id,
            character_id=snapshot.scope.character_id,
            context_snapshot_id=snapshot.snapshot_id,
            snapshot_fingerprint=content_fingerprint(snapshot.model_dump(mode="json")),
            source_scope=scope,
            now_utc=now,
            trace_id=uuid4(),
        )
        pending = []
        for definition_node in definition.nodes:
            task_id = uuid4()
            node_input = prepare_node_input(
                snapshot,
                graph_run_id=str(run.graph_run_id),
                node_task_id=str(task_id),
                node_key=definition_node.node_key,
                node_kind=definition_node.node_kind,
            )
            node = ReflectionNodeTask.create(
                task_id=task_id,
                graph_run_id=run.graph_run_id,
                node_key=definition_node.node_key,
                node_kind=definition_node.node_kind,
                dependency_keys=definition.dependency_keys_for(definition_node.node_key),
                node_input_fingerprint=content_fingerprint(node_input.model_dump(mode="json")),
                output_contract=definition_node.output_contract,
                now_utc=now,
                activated=definition.is_activated(definition_node.node_key, ()),
            )
            run = run.register_task(node, now_utc=now)
            pending.append(node)
        self.runs.add(connection, run, snapshot)
        for node in pending:
            self.nodes.add(connection, node)
        enqueue_trace(
            connection,
            str(uuid4()),
            str(run.trace_id),
            "reflection.graph.started",
            "reflection_graph",
            str(run.graph_run_id),
            {
                "graph_kind": run.graph_kind.value,
                "graph_version": run.graph_version,
                "source_count": len(scope.sources),
            },
            now,
        )
        return run
