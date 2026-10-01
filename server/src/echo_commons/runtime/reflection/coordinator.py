from __future__ import annotations

from collections.abc import Callable, Sequence
from dataclasses import dataclass
from datetime import datetime
from uuid import NAMESPACE_URL, UUID, uuid5

import aiosqlite
from pydantic import ValidationError

from echo_commons.agents.contracts import GraphContextSnapshot, SegmentSummaryAction
from echo_commons.domain.errors import DomainInvariantError, require_utc
from echo_commons.domain.reflection_graph import (
    ArtifactRef,
    OutputContractRef,
    ReflectionArtifact,
    ReflectionDependencyMode,
    ReflectionGraphDefinition,
    ReflectionGraphKind,
    ReflectionGraphRun,
    ReflectionGraphRunStatus,
    ReflectionNodeDefinition,
    ReflectionSourceScope,
    content_fingerprint,
)
from echo_commons.domain.reflection_node import ReflectionNodeTask, ReflectionNodeTaskStatus
from echo_commons.domain.reflection_rules import should_activate_follow_up
from echo_commons.runtime.modules import ReflectionModule
from echo_commons.runtime.reflection.context import (
    GraphSnapshotAssembler,
    GraphSnapshotBuild,
    SnapshotBuildContext,
)
from echo_commons.runtime.reflection.continuity_context import (
    ContinuityCompressionGraphSnapshotBuilder,
    ContinuityCompressionSnapshotPayload,
)
from echo_commons.runtime.reflection.memory_context import (
    MemoryOrganizationGraphSnapshotBuilder,
    MemoryOrganizationSnapshotPayload,
)
from echo_commons.runtime.reflection.node_input import NodeInputProjector
from echo_commons.runtime.reflection.registry import ReflectionGraphRegistry
from echo_commons.runtime.reflection.segment_context import (
    SegmentGraphSnapshotBuilder,
    SegmentSnapshotPayload,
)
from echo_commons.infrastructure.models import resolve_agent_route


class ReflectionGraphSnapshotStale(RuntimeError):
    """The durable graph input cannot be rebuilt without source drift."""

    code = "reflection_graph_snapshot_stale"


@dataclass(frozen=True, slots=True)
class ReflectionGraphStart:
    """The graph run and root nodes created from one reflection source."""

    graph_run: ReflectionGraphRun
    snapshot_build: GraphSnapshotBuild
    root_tasks: tuple[ReflectionNodeTask, ...]


ActivationPolicy = Callable[[ReflectionNodeDefinition, GraphContextSnapshot], bool]


class ReflectionCoordinator:
    """Own graph identity, root creation, and dependency-driven successors."""

    def __init__(
        self,
        runtime: ReflectionModule,
        *,
        registry: ReflectionGraphRegistry | None = None,
        activation_policy: ActivationPolicy | None = None,
    ) -> None:
        self.runtime = runtime
        self.registry = registry or ReflectionGraphRegistry()
        self.activation_policy = activation_policy or (lambda _node, _snapshot: True)
        assembler = GraphSnapshotAssembler(
            runtime,
            max_materials=runtime.settings.reflection_max_materials,
            max_material_chars=runtime.settings.reflection_max_material_chars,
        )
        self.snapshot_builders = {
            ReflectionGraphKind.SEGMENT_REFLECT: SegmentGraphSnapshotBuilder(
                runtime,
                assembler=assembler,
            ),
            ReflectionGraphKind.MEMORY_ORGANIZE: MemoryOrganizationGraphSnapshotBuilder(
                runtime,
                assembler=assembler,
            ),
            ReflectionGraphKind.CONTINUITY_COMPRESS: ContinuityCompressionGraphSnapshotBuilder(
                assembler=assembler,
            ),
        }
        self.node_input_projector = NodeInputProjector()
        self.graph_runs = runtime.reflection_graph_runs
        self.node_tasks = runtime.reflection_graph_nodes
        self.artifacts = runtime.reflection_graph_artifacts
        self._definition_cache: dict[tuple[str, str], ReflectionGraphDefinition] = {}

    def definition_for(self, run: ReflectionGraphRun) -> ReflectionGraphDefinition:
        key = (str(getattr(run.graph_kind, "value", run.graph_kind)), run.graph_version)
        definition = self._definition_cache.get(key)
        if definition is None:
            definition = self.registry.require(*key)
            self._definition_cache[key] = definition
        return definition

    async def start_segment(
        self,
        segment_id: UUID,
        *,
        now_utc: datetime | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionGraphStart:
        """Create or return the segment graph and its root nodes."""

        if not isinstance(segment_id, UUID):
            raise TypeError("segment_id must be a UUID")
        await self.runtime.ensure_started()
        now = require_utc(now_utc or self.runtime.clock(), "now_utc")
        return await self._start_graph(
            ReflectionGraphKind.SEGMENT_REFLECT,
            SegmentSnapshotPayload(segment_id),
            now_utc=now,
            connection=connection,
        )

    async def start_memory_organization(
        self,
        payload: MemoryOrganizationSnapshotPayload,
        *,
        now_utc: datetime | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionGraphStart:
        """Create or return the graph for one frozen summary batch."""

        await self.runtime.ensure_started()
        now = require_utc(now_utc or self.runtime.clock(), "now_utc")
        return await self._start_graph(
            ReflectionGraphKind.MEMORY_ORGANIZE,
            payload,
            now_utc=now,
            connection=connection,
        )

    async def start_continuity_compression(
        self,
        payload: ContinuityCompressionSnapshotPayload,
        *,
        now_utc: datetime | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> ReflectionGraphStart:
        """Create or return the graph for one frozen continuity batch."""

        await self.runtime.ensure_started()
        now = require_utc(now_utc or self.runtime.clock(), "now_utc")
        return await self._start_graph(
            ReflectionGraphKind.CONTINUITY_COMPRESS,
            payload,
            now_utc=now,
            connection=connection,
        )

    async def _start_graph(
        self,
        graph_kind: ReflectionGraphKind,
        payload: object,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection | None,
    ) -> ReflectionGraphStart:
        definition = self.registry.require(graph_kind)
        if connection is None:
            async with self.runtime.database.transaction() as read_connection:
                snapshot_build = await self._build_snapshot(
                    graph_kind,
                    payload,
                    context=SnapshotBuildContext(now_utc=now_utc, connection=read_connection),
                )
        else:
            snapshot_build = await self._build_snapshot(
                graph_kind,
                payload,
                context=SnapshotBuildContext(now_utc=now_utc, connection=connection),
            )

        graph_run_id = _graph_run_id(
            graph_kind=definition.graph_kind,
            graph_version=definition.version,
            account_id=snapshot_build.snapshot.account_id,
            character_id=snapshot_build.snapshot.character_id,
            source_scope=snapshot_build.source_scope,
        )
        existing_run = await self.graph_runs.get(graph_run_id, connection=connection)
        if existing_run is not None and existing_run.status is ReflectionGraphRunStatus.FAILED:
            if connection is None:
                async with self.runtime.database.transaction() as read_connection:
                    snapshot_build = await self.load_snapshot(
                        existing_run, connection=read_connection
                    )
            else:
                snapshot_build = await self.load_snapshot(existing_run, connection=connection)
        run = ReflectionGraphRun.create(
            graph_run_id=graph_run_id,
            definition=definition,
            account_id=snapshot_build.snapshot.account_id,
            character_id=snapshot_build.snapshot.character_id,
            context_snapshot_id=snapshot_build.snapshot.snapshot_id,
            snapshot_fingerprint=snapshot_build.snapshot.snapshot_fingerprint,
            source_scope=snapshot_build.source_scope,
            trace_id=uuid5(NAMESPACE_URL, f"reflection-trace:{graph_run_id}"),
            now_utc=now_utc,
        )
        root_tasks = tuple(
            self._task_from_input(
                run,
                definition.node(node_key),
                self.node_input_projector.project(
                    snapshot_build.snapshot,
                    definition.node(node_key),
                    model_profile=self._model_profile(),
                ),
                now_utc,
            )
            for node_key in definition.root_node_keys
        )

        async def persist_start(
            write_connection: aiosqlite.Connection,
        ) -> ReflectionGraphStart:
            stored_run, stored_roots = await self.graph_runs.ensure_with_root_tasks(
                run,
                root_tasks,
                now_utc=now_utc,
                connection=write_connection,
            )
            return ReflectionGraphStart(stored_run, snapshot_build, stored_roots)

        if connection is not None:
            return await persist_start(connection)
        async with self.runtime.database.transaction(immediate=True) as write_connection:
            return await persist_start(write_connection)

    async def _build_snapshot(
        self,
        graph_kind: ReflectionGraphKind,
        payload: object,
        *,
        context: SnapshotBuildContext,
    ) -> GraphSnapshotBuild:
        builder = self.snapshot_builders[graph_kind]
        return await builder.build(payload, context=context)

    async def load_snapshot(
        self,
        run: ReflectionGraphRun,
        *,
        connection: aiosqlite.Connection,
    ) -> GraphSnapshotBuild:
        """Rebuild at graph creation time and reject source drift."""

        graph_kind = ReflectionGraphKind(run.graph_kind)
        if graph_kind is ReflectionGraphKind.SEGMENT_REFLECT:
            sources = tuple(
                source for source in run.source_scope.sources if source.kind == "memory_segment"
            )
            if len(sources) != 1:
                raise ReflectionGraphSnapshotStale(
                    "graph source scope has no unique segment source"
                )
            try:
                payload: object = SegmentSnapshotPayload(UUID(sources[0].ref))
            except ValueError as exc:
                raise ReflectionGraphSnapshotStale("graph source reference is invalid") from exc
        elif graph_kind is ReflectionGraphKind.MEMORY_ORGANIZE:
            sources = tuple(
                source
                for source in run.source_scope.sources
                if source.kind == "memory_summary_batch"
            )
            if len(sources) != 1:
                raise ReflectionGraphSnapshotStale(
                    "graph source scope has no unique summary batch source"
                )
            payload = MemoryOrganizationSnapshotPayload(
                batch_id=sources[0].ref,
                account_id=run.account_id,
                character_id=run.character_id,
            )
        elif graph_kind is ReflectionGraphKind.CONTINUITY_COMPRESS:
            sources = tuple(
                source
                for source in run.source_scope.sources
                if source.kind == "memory_summary_batch"
            )
            if len(sources) != 1:
                raise ReflectionGraphSnapshotStale(
                    "graph source scope has no unique summary batch source"
                )
            payload = ContinuityCompressionSnapshotPayload(
                batch_id=sources[0].ref,
                account_id=run.account_id,
                character_id=run.character_id,
            )
        else:
            raise ReflectionGraphSnapshotStale("unsupported reflection graph kind")
        try:
            actual = await self._build_snapshot(
                graph_kind,
                payload,
                context=SnapshotBuildContext(
                    now_utc=run.created_at_utc,
                    connection=connection,
                ),
            )
        except (LookupError, DomainInvariantError, ValueError) as exc:
            raise ReflectionGraphSnapshotStale(str(exc)) from exc
        if (
            actual.snapshot.snapshot_id != run.context_snapshot_id
            or actual.snapshot.snapshot_fingerprint != run.snapshot_fingerprint.value
            or not source_scopes_equal(actual.source_scope, run.source_scope)
        ):
            raise ReflectionGraphSnapshotStale("graph snapshot or source scope changed")
        return actual

    async def materialize_successors(
        self,
        run: ReflectionGraphRun,
        snapshot: GraphContextSnapshot,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection,
    ) -> tuple[ReflectionGraphRun, tuple[ReflectionNodeTask, ...]]:
        """Create ready successors after predecessor Artifacts are durable."""

        current_run = await self.graph_runs.get(run.graph_run_id, connection=connection)
        if current_run is None:
            raise LookupError("reflection_graph_run_not_found")
        if current_run.status is not ReflectionGraphRunStatus.RUNNING:
            return current_run, await self.node_tasks.list_for_graph(
                current_run.graph_run_id,
                connection,
            )
        definition = self.definition_for(current_run)
        tasks = list(await self.node_tasks.list_for_graph(current_run.graph_run_id, connection))
        task_by_key = {task.node_key: task for task in tasks}
        changed = False
        expected_updated = current_run.updated_at_utc
        model_profile = self._model_profile()

        for node in definition.nodes:
            if node.node_key in task_by_key:
                continue
            dependencies = definition.dependencies_for(node.node_key)
            if not dependencies:
                continue
            upstream = [task_by_key.get(edge.upstream_node_key) for edge in dependencies]
            if any(task is None for task in upstream):
                continue
            upstream_tasks = [task for task in upstream if task is not None]
            if any(not task.is_terminal for task in upstream_tasks):
                continue
            if not self._dependencies_ready(dependencies, upstream_tasks):
                continue

            predecessor_artifacts: list[ReflectionArtifact] = []
            predecessor_refs: list[ArtifactRef] = []
            for edge in sorted(dependencies, key=lambda item: item.upstream_node_key):
                predecessor = task_by_key[edge.upstream_node_key]
                if predecessor.status is not ReflectionNodeTaskStatus.COMPLETED:
                    continue
                if predecessor.artifact_id is None:
                    raise DomainInvariantError("completed predecessor has no Artifact")
                artifact = await self.artifacts.get(predecessor.artifact_id, connection=connection)
                if artifact is None:
                    raise DomainInvariantError("completed predecessor Artifact is missing")
                predecessor_artifacts.append(artifact)
                predecessor_refs.append(artifact.reference)
            activated = True
            if not node.required and any(
                edge.mode is ReflectionDependencyMode.CONDITIONAL for edge in dependencies
            ):
                requested = self._follow_up_requested(
                    node.node_key,
                    tuple(predecessor_artifacts),
                )
                target_available = self._follow_up_target_available(node.node_key, snapshot)
                activated = should_activate_follow_up(
                    node.node_key,
                    requested=requested,
                    has_window_material=snapshot.has_window_material,
                    target_available=target_available,
                    policy_allowed=bool(self.activation_policy(node, snapshot)),
                )
            node_input = self.node_input_projector.project(
                snapshot,
                node,
                predecessor_artifacts=tuple(predecessor_artifacts),
                model_profile=model_profile,
            )
            task = self._task_from_input(
                current_run,
                node,
                node_input,
                now_utc,
                input_artifact_refs=tuple(predecessor_refs),
                activated=activated,
            )
            if not activated:
                task = task.skip(now_utc=now_utc, reason_code="conditional_policy_disabled")
            stored = await self.node_tasks.ensure(task, connection=connection)
            task_by_key[stored.node_key] = stored
            tasks.append(stored)
            current_run = current_run.register_task(stored, now_utc=now_utc)
            changed = True

        if changed:
            current_run = await self.graph_runs.save(
                current_run,
                expected_updated_at_utc=expected_updated,
                connection=connection,
            )
        return current_run, tuple(tasks)

    @staticmethod
    def _follow_up_requested(
        node_key: str,
        predecessor_artifacts: Sequence[ReflectionArtifact],
    ) -> bool:
        if node_key not in {"relationship_reflect", "state_reflect"}:
            raise DomainInvariantError(f"unsupported follow-up node: {node_key}")
        if len(predecessor_artifacts) != 1:
            raise DomainInvariantError("follow-up node requires one summary Artifact")
        payload = predecessor_artifacts[0].payload.to_dict()
        if payload.get("kind") == "no_op":
            return False
        try:
            action = SegmentSummaryAction.model_validate(payload)
        except ValidationError as exc:
            raise DomainInvariantError(
                "summary Artifact has an invalid follow-up decision"
            ) from exc
        return (
            action.follow_up.relationship_reflect
            if node_key == "relationship_reflect"
            else action.follow_up.state_reflect
        )

    @staticmethod
    def _follow_up_target_available(node_key: str, snapshot: GraphContextSnapshot) -> bool:
        if node_key == "relationship_reflect":
            return bool(snapshot.relationship_state.subject_id.strip())
        if node_key == "state_reflect":
            return bool(snapshot.character_state.character_id.strip())
        raise DomainInvariantError(f"unsupported follow-up node: {node_key}")

    @staticmethod
    def _dependencies_ready(
        dependencies: Sequence[object],
        upstream_tasks: Sequence[ReflectionNodeTask],
    ) -> bool:
        by_key = {task.node_key: task for task in upstream_tasks}
        for edge in dependencies:
            task = by_key[edge.upstream_node_key]
            if task.status is ReflectionNodeTaskStatus.COMPLETED:
                continue
            if edge.mode is ReflectionDependencyMode.CONDITIONAL and task.status in {
                ReflectionNodeTaskStatus.SKIPPED,
                ReflectionNodeTaskStatus.FAILED,
            }:
                continue
            return False
        return True

    def _task_from_input(
        self,
        run: ReflectionGraphRun,
        node: ReflectionNodeDefinition,
        node_input: object,
        now_utc: datetime,
        *,
        input_artifact_refs: Sequence[ArtifactRef] = (),
        activated: bool = True,
    ) -> ReflectionNodeTask:
        dependencies = self.definition_for(run).dependencies_for(node.node_key)
        return ReflectionNodeTask.create(
            task_id=uuid5(NAMESPACE_URL, f"reflection-node:{run.graph_run_id}:{node.node_key}"),
            graph_run_id=run.graph_run_id,
            node_key=node.node_key,
            node_kind=node.node_kind,
            dependency_keys=tuple(edge.upstream_node_key for edge in dependencies),
            node_input_fingerprint=node_input.node_input_fingerprint,
            output_contract=OutputContractRef(
                kind=node.output_contract.kind,
                version=node.output_contract.version,
            ),
            now_utc=now_utc,
            input_artifact_refs=input_artifact_refs,
            activated=activated,
        )

    def _model_profile(self) -> str:
        return resolve_agent_route(self.runtime.agent, "character.reflection").resolved_profile


def _graph_run_id(
    *,
    graph_kind: object,
    graph_version: str,
    account_id: str,
    character_id: str,
    source_scope: ReflectionSourceScope,
) -> UUID:
    payload = {
        "graph_kind": str(getattr(graph_kind, "value", graph_kind)),
        "graph_version": graph_version,
        "account_id": account_id,
        "character_id": character_id,
        "sources": [
            {"kind": source.kind, "ref": source.ref, "version": source.version}
            for source in sorted(source_scope.sources, key=lambda item: item.identity)
        ],
    }
    return uuid5(NAMESPACE_URL, f"reflection-graph:{content_fingerprint(payload).value}")


def source_scopes_equal(
    left: ReflectionSourceScope,
    right: ReflectionSourceScope,
) -> bool:
    """Compare a source boundary by identity, kind, reference, and version."""

    return {(item.kind, item.ref, item.version) for item in left.sources} == {
        (item.kind, item.ref, item.version) for item in right.sources
    }


__all__ = [
    "ReflectionCoordinator",
    "ReflectionGraphSnapshotStale",
    "ReflectionGraphStart",
    "source_scopes_equal",
]
