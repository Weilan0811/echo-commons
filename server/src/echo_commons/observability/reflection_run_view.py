"""Read model for diagnosing one Reflection graph run."""

from __future__ import annotations

from collections.abc import Mapping
from dataclasses import dataclass, fields, is_dataclass
from datetime import date, datetime, time
from enum import Enum
from uuid import UUID

import aiosqlite

from echo_server.domain.reflection_graph import ReflectionArtifact, ReflectionGraphRun
from echo_server.domain.reflection_node import ReflectionNodeTask
from echo_server.domain.reflection_result import GraphReviewRecord
from echo_server.observability.trace import TraceQueryService
from echo_server.store.database import Database
from echo_server.store.reflection_graph_repositories import (
    GraphReviewRepository,
    ReflectionArtifactRepository,
    ReflectionGraphRunRepository,
    ReflectionNodeTaskRepository,
)
from echo_server.store.trace_repository import TraceRecord


@dataclass(frozen=True, slots=True)
class ReflectionFactView:
    """One authoritative fact written from the graph run."""

    fact_kind: str
    fact_id: str
    source_ref: str
    payload: dict[str, object]


@dataclass(frozen=True, slots=True)
class ReflectionRunView:
    """Joined diagnostic view from graph runtime through committed facts."""

    graph_run: ReflectionGraphRun
    node_tasks: tuple[ReflectionNodeTask, ...]
    artifacts: tuple[ReflectionArtifact, ...]
    result: GraphReviewRecord | None
    facts: tuple[ReflectionFactView, ...]
    traces: tuple[TraceRecord, ...]

    def to_payload(self) -> dict[str, object]:
        return {
            "graphRun": _jsonable(self.graph_run),
            "nodeTasks": _jsonable(self.node_tasks),
            "artifacts": _jsonable(self.artifacts),
            "result": _jsonable(self.result),
            "facts": _jsonable(self.facts),
            "traces": _jsonable(self.traces),
        }


class ReflectionRunViewService:
    """Load one graph run and all diagnostic links in one read transaction."""

    def __init__(
        self,
        database: Database,
        *,
        graph_runs: ReflectionGraphRunRepository,
        node_tasks: ReflectionNodeTaskRepository,
        artifacts: ReflectionArtifactRepository,
        results: GraphReviewRepository,
        traces: TraceQueryService,
    ) -> None:
        self.database = database
        self.graph_runs = graph_runs
        self.node_tasks = node_tasks
        self.artifacts = artifacts
        self.results = results
        self.traces = traces

    async def get(self, graph_run_id: UUID) -> ReflectionRunView | None:
        async with self.database.transaction() as connection:
            run = await self.graph_runs.get(graph_run_id, connection=connection)
            if run is None:
                return None
            node_tasks = await self.node_tasks.list_for_graph(
                graph_run_id,
                connection,
            )
            artifacts = await self.artifacts.list_for_graph(
                graph_run_id,
                connection=connection,
            )
            result = await self.results.get_for_graph(
                graph_run_id,
                connection=connection,
            )
            traces = (
                await self.traces.by_correlation(run.trace_id, connection=connection)
                if run.trace_id is not None
                else await self.traces.by_entity(
                    "reflection_graph_run",
                    str(graph_run_id),
                    connection=connection,
                )
            )
            facts = await self._facts(run, connection)
        return ReflectionRunView(
            graph_run=run,
            node_tasks=node_tasks,
            artifacts=artifacts,
            result=result,
            facts=facts,
            traces=traces,
        )

    async def _facts(
        self,
        run: ReflectionGraphRun,
        connection: aiosqlite.Connection,
    ) -> tuple[ReflectionFactView, ...]:
        facts: list[ReflectionFactView] = []
        segment_id = next(
            (source.ref for source in run.source_scope.sources if source.kind == "memory_segment"),
            None,
        )
        if segment_id is not None:
            row = await _fetch_one(
                connection,
                "SELECT * FROM memory_segments WHERE segment_id = ?",
                (segment_id,),
            )
            if row is not None:
                facts.append(
                    ReflectionFactView(
                        fact_kind="segment",
                        fact_id=segment_id,
                        source_ref=f"memory_segment:{segment_id}",
                        payload=dict(row),
                    )
                )

        source_pattern = f"reflection:{run.graph_run_id}:%"
        relation_rows = await _fetch_all(
            connection,
            "SELECT * FROM relation_evidence WHERE source_kind = 'reflection' "
            "AND source_ref LIKE ? ORDER BY recorded_at_utc, evidence_id",
            (source_pattern,),
        )
        facts.extend(
            ReflectionFactView(
                fact_kind="relationship_evidence",
                fact_id=row["evidence_id"],
                source_ref=row["source_ref"],
                payload=dict(row),
            )
            for row in relation_rows
        )

        state_rows = await _fetch_all(
            connection,
            "SELECT * FROM character_state_entries WHERE source_kind = 'reflection' "
            "AND source_ref LIKE ? ORDER BY recorded_at_utc, entry_id",
            (source_pattern,),
        )
        facts.extend(
            ReflectionFactView(
                fact_kind="character_state",
                fact_id=row["entry_id"],
                source_ref=row["source_ref"],
                payload=dict(row),
            )
            for row in state_rows
        )
        return tuple(facts)


async def _fetch_one(
    connection: aiosqlite.Connection,
    query: str,
    parameters: tuple[object, ...],
) -> aiosqlite.Row | None:
    cursor = await connection.execute(query, parameters)
    try:
        return await cursor.fetchone()
    finally:
        await cursor.close()


async def _fetch_all(
    connection: aiosqlite.Connection,
    query: str,
    parameters: tuple[object, ...],
) -> list[aiosqlite.Row]:
    cursor = await connection.execute(query, parameters)
    try:
        return await cursor.fetchall()
    finally:
        await cursor.close()


def _jsonable(value: object) -> object:
    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, Enum):
        return value.value
    if isinstance(value, Mapping):
        return {str(key): _jsonable(item) for key, item in value.items()}
    if isinstance(value, (list, tuple, set, frozenset)):
        return [_jsonable(item) for item in value]
    if is_dataclass(value):
        return {field.name: _jsonable(getattr(value, field.name)) for field in fields(value)}
    if hasattr(value, "model_dump"):
        return _jsonable(value.model_dump(mode="json"))
    return str(value)


__all__ = ["ReflectionFactView", "ReflectionRunView", "ReflectionRunViewService"]
