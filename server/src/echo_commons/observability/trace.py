"""Shared Trace ports, payload policy and durable query access."""

from __future__ import annotations

from datetime import datetime
from typing import Any, Protocol
from uuid import UUID

import aiosqlite

from echo_server.store.trace_repository import TraceRecord, TraceRepository

_AGENT_STARTED_FIELDS = frozenset(
    {
        "attempt_count",
        "agent_id",
        "task_kind",
        "requested_model_profile",
        "model_profile",
        "route_fallback",
    }
)
_AGENT_COMPLETED_FIELDS = frozenset(
    {
        "agent_id",
        "invocation_id",
        "baseline_resource_id",
        "baseline_version",
        "harness_version",
        "identity_resource_id",
        "identity_version",
        "task_kind",
        "requested_model_profile",
        "model_profile",
        "route_fallback",
        "output_schema",
        "prompt_layout_version",
        "run_status",
        "stop_reason",
        "step_count",
        "model_request_count",
        "tool_call_count",
        "input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "output_tokens",
        "total_tokens",
        "cache_hit_ratio",
        "repair_count",
    }
)
_AGENT_FAILED_FIELDS = frozenset({"error_code", "attempt_count"})
_AGENT_STEP_FIELDS = frozenset(
    {
        "step_index",
        "response_kind",
        "duration_ms",
        "tool_call_count",
        "model_request_count",
        "input_tokens",
        "cache_read_tokens",
        "cache_write_tokens",
        "output_tokens",
        "total_tokens",
        "progressed",
        "new_item_count",
    }
)
_AGENT_TOOL_FIELDS = frozenset(
    {
        "tool_name",
        "ok",
        "error_code",
        "duration_ms",
        "progressed",
        "new_item_count",
        "no_progress_streak",
    }
)
_TASK_FIELDS = frozenset(
    {
        "attempt_count",
        "error_code",
        "decision_code",
        "stop_reason",
        "context_version",
    }
)
_REFLECTION_GRAPH_COMPLETED_FIELDS = frozenset(
    {
        "outcome",
        "artifact_count",
        "aggregate_fingerprint",
        "decision",
        "decision_code",
        "partial",
    }
)
_REFLECTION_GRAPH_STARTED_FIELDS = frozenset(
    {"graph_kind", "graph_version", "execution_generation", "source_count"}
)
_REFLECTION_GRAPH_REVIEWED_FIELDS = frozenset(
    {"decision", "decision_code", "artifact_count", "partial"}
)
_REFLECTION_GRAPH_FAILED_FIELDS = frozenset({"error_code", "execution_generation"})
_REFLECTION_FACTS_COMMITTED_FIELDS = frozenset(
    {
        "summary_count",
        "digest_count",
        "relationship_count",
        "state_count",
        "memory_count",
        "entity_count",
        "edge_count",
        "fact_count",
    }
)
_REFLECTION_NODE_CLAIMED_FIELDS = frozenset({"graph_run_id", "node_key", "attempt_count"})
_REFLECTION_NODE_RETRY_FIELDS = frozenset({"error_code"})


class AgentTraceRecorder(Protocol):
    """Port for Agent invocation, model and tool lifecycle events."""

    async def enqueue(
        self,
        *,
        trace_id: UUID,
        correlation_id: UUID,
        kind: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
        created_at: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        """Enqueue one safe Agent event."""


class TaskTraceRecorder(Protocol):
    """Port for durable task and graph lifecycle events."""

    async def enqueue(
        self,
        *,
        trace_id: UUID,
        correlation_id: UUID,
        kind: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
        created_at: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        """Enqueue one safe task event."""


class TraceQueryService:
    """Read materialized Trace history without exposing the outbox."""

    def __init__(self, repository: TraceRepository) -> None:
        self.repository = repository

    async def by_correlation(
        self,
        correlation_id: UUID,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[TraceRecord, ...]:
        return await self.repository.list_by_correlation(
            correlation_id,
            connection=connection,
        )

    async def by_entity(
        self,
        entity_type: str,
        entity_id: str,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[TraceRecord, ...]:
        return await self.repository.list_by_entity(
            entity_type,
            entity_id,
            connection=connection,
        )


def safe_trace_payload(event_kind: str, **values: Any) -> dict[str, Any]:
    """Validate and bound the scalar payload allowed for one event kind."""

    allowed = _allowed_fields(event_kind)
    unknown = set(values) - allowed
    if unknown:
        names = ", ".join(sorted(unknown))
        raise ValueError(f"trace event {event_kind} does not allow fields: {names}")
    payload: dict[str, Any] = {}
    for key, value in values.items():
        if value is None:
            continue
        if not isinstance(value, (str, int, float, bool)):
            raise TypeError(f"trace field {key} must be a scalar")
        payload[key] = value[:256] if isinstance(value, str) else value
    return payload


def _allowed_fields(event_kind: str) -> frozenset[str]:
    exact = {
        "agent.started": _AGENT_STARTED_FIELDS,
        "agent.completed": _AGENT_COMPLETED_FIELDS,
        "agent.failed": _AGENT_FAILED_FIELDS,
        "agent.step.completed": _AGENT_STEP_FIELDS,
        "agent.tool.completed": _AGENT_TOOL_FIELDS,
        "agent.tool.failed": _AGENT_TOOL_FIELDS,
        "reflection_graph.started": _REFLECTION_GRAPH_STARTED_FIELDS,
        "reflection_graph.completed": _REFLECTION_GRAPH_COMPLETED_FIELDS,
        "reflection_graph.partial": _REFLECTION_GRAPH_COMPLETED_FIELDS,
        "reflection_graph.reviewed": _REFLECTION_GRAPH_REVIEWED_FIELDS,
        "reflection_graph.failed": _REFLECTION_GRAPH_FAILED_FIELDS,
        "reflection_facts.committed": _REFLECTION_FACTS_COMMITTED_FIELDS,
        "reflection_graph_node.claimed": _REFLECTION_NODE_CLAIMED_FIELDS,
        "input_batch.terminal_failed": frozenset({"error_code"}),
    }.get(event_kind)
    if exact is not None:
        return exact
    if event_kind.startswith("agent_result."):
        return frozenset({"decision_code", "context_version", "error_code"})
    if event_kind.startswith("reflection_graph_node."):
        return _REFLECTION_NODE_RETRY_FIELDS
    if event_kind.startswith("task."):
        return _TASK_FIELDS
    if event_kind.startswith("input_preparation."):
        return frozenset({"error_code"})
    if event_kind.startswith("input_batch.") or event_kind.startswith("message."):
        return frozenset()
    raise ValueError(f"trace event kind is not registered: {event_kind}")


__all__ = [
    "AgentTraceRecorder",
    "TaskTraceRecorder",
    "TraceQueryService",
    "safe_trace_payload",
]
