"""Persistent-task adapter for Reflection graph NodeTasks."""

from __future__ import annotations

from datetime import datetime, timedelta
from uuid import NAMESPACE_URL, uuid5

from echo_server.domain.reflection_node import ReflectionNodeTask
from echo_server.observability.trace import safe_trace_payload
from echo_server.runtime.dispatcher.contracts import (
    PersistentTaskStore,
    TaskClaimScope,
    TaskLease,
)
from echo_server.runtime.modules import ReflectionModule


class ReflectionGraphTaskStore(PersistentTaskStore):
    """Reuse the generic dispatcher while keeping graph state canonical."""

    task_kind = "reflection.graph.node"

    def __init__(self, runtime: ReflectionModule) -> None:
        self.runtime = runtime

    async def recover_expired(self, now_utc: datetime) -> int:
        await self.runtime.ensure_started()
        async with self.runtime.database.transaction(immediate=True) as connection:
            return await self.runtime.reflection_graph_nodes.recover_expired(
                now_utc,
                connection=connection,
            )

    async def claim_next(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        scope: TaskClaimScope | None = None,
    ) -> TaskLease | None:
        if worker_id != self.runtime.reflection_graph_worker_id:
            raise ValueError("reflection graph task store is bound to its graph worker")
        account_id = (
            scope.account_id
            if scope is not None and scope.account_id is not None
            else self.runtime.settings.account_id
        )
        character_id = scope.scope_key if scope is not None else None
        await self.runtime.ensure_started()
        async with self.runtime.database.transaction(immediate=True) as connection:
            task = await self.runtime.reflection_graph_nodes.claim_next_ready(
                account_id=account_id,
                character_id=character_id,
                worker_id=worker_id,
                now_utc=now_utc,
                lease_seconds=self.runtime.settings.lease_seconds,
                connection=connection,
            )
            if task is not None:
                run = await self.runtime.reflection_graph_runs.get(
                    task.graph_run_id,
                    connection=connection,
                )
                if run is None:
                    raise RuntimeError("claimed graph NodeTask has no GraphRun")
                await self.runtime.task_traces.enqueue(
                    trace_id=uuid5(NAMESPACE_URL, f"reflection-graph-claimed:{task.task_id}"),
                    correlation_id=run.trace_id or task.task_id,
                    kind="reflection_graph_node.claimed",
                    entity_type="reflection_node_task",
                    entity_id=str(task.task_id),
                    payload=safe_trace_payload(
                        "reflection_graph_node.claimed",
                        graph_run_id=str(task.graph_run_id),
                        node_key=task.node_key,
                        attempt_count=task.attempt_count,
                    ),
                    created_at=now_utc,
                    connection=connection,
                )
        if task is None:
            return None
        if task.lease_until_utc is None or task.lease_owner is None:
            raise RuntimeError("claimed graph NodeTask has no lease")
        run_id = task.graph_run_id
        run = await self.runtime.reflection_graph_runs.get(run_id)
        correlation_id = (
            run.trace_id
            if run is not None and run.trace_id is not None
            else uuid5(NAMESPACE_URL, f"reflection-graph:{run_id}")
        )
        return TaskLease(
            task_id=task.task_id,
            task_kind=self.task_kind,
            correlation_id=correlation_id,
            scope_key=str(run_id),
            attempt_count=task.attempt_count,
            lease_generation=task.lease_generation,
            lease_owner=task.lease_owner,
            lease_until_utc=task.lease_until_utc,
            payload=task,
        )

    async def reschedule(
        self,
        lease: TaskLease,
        *,
        error_code: str,
        terminal: bool = False,
    ) -> None:
        task = lease.payload
        if not isinstance(task, ReflectionNodeTask):
            raise TypeError("reflection graph lease has an invalid payload")
        now = self.runtime.clock()
        async with self.runtime.database.transaction(immediate=True) as connection:
            current = await self.runtime.reflection_graph_nodes.get(
                task.task_id,
                connection=connection,
            )
            if current is None or not current.has_valid_lease(
                worker_id=lease.lease_owner,
                now_utc=now,
                attempt_count=lease.attempt_count,
                lease_generation=lease.lease_generation,
            ):
                return
            updated = await self.runtime.reflection_graph_nodes.retry_or_fail(
                task.task_id,
                worker_id=lease.lease_owner,
                now_utc=now,
                available_at_utc=(
                    now
                    if terminal
                    else now + timedelta(seconds=self.runtime.settings.retry_backoff_seconds)
                ),
                error_code=error_code,
                max_attempts=1 if terminal else self.runtime.settings.max_agent_attempts,
                attempt_count=lease.attempt_count,
                lease_generation=lease.lease_generation,
                connection=connection,
            )
            if updated.status.value == "failed":
                run = await self.runtime.reflection_graph_runs.get(
                    task.graph_run_id,
                    connection=connection,
                )
                if run is not None and not run.is_terminal:
                    node = self.runtime.reflection_graph_coordinator.definition_for(run).node(
                        task.node_key
                    )
                    if node.required:
                        failed = run.fail(now_utc=now, error_code=error_code)
                        await self.runtime.reflection_graph_runs.save(
                            failed,
                            expected_updated_at_utc=run.updated_at_utc,
                            connection=connection,
                        )
                        await self.runtime.task_traces.enqueue(
                            trace_id=uuid5(
                                NAMESPACE_URL,
                                f"reflection-graph-failed:{failed.graph_run_id}:{failed.execution_generation}",
                            ),
                            correlation_id=failed.trace_id or failed.graph_run_id,
                            kind="reflection_graph.failed",
                            entity_type="reflection_graph_run",
                            entity_id=str(failed.graph_run_id),
                            payload=safe_trace_payload(
                                "reflection_graph.failed",
                                error_code=error_code,
                                execution_generation=failed.execution_generation,
                            ),
                            created_at=now,
                            connection=connection,
                        )
                    else:
                        snapshot = await self.runtime.reflection_graph_coordinator.load_snapshot(
                            run,
                            connection=connection,
                        )
                        await self.runtime.reflection_graph_coordinator.materialize_successors(
                            run,
                            snapshot.snapshot,
                            now_utc=now,
                            connection=connection,
                        )
            run = await self.runtime.reflection_graph_runs.get(
                task.graph_run_id,
                connection=connection,
            )
            await self.runtime.task_traces.enqueue(
                trace_id=uuid5(
                    NAMESPACE_URL,
                    f"reflection-graph-rescheduled:{task.task_id}:{updated.attempt_count}",
                ),
                correlation_id=(run.trace_id if run and run.trace_id else task.task_id),
                kind=(
                    "reflection_graph_node.failed"
                    if updated.status.value == "failed"
                    else "reflection_graph_node.retry_scheduled"
                ),
                entity_type="reflection_node_task",
                entity_id=str(task.task_id),
                payload=safe_trace_payload(
                    "reflection_graph_node.failed"
                    if updated.status.value == "failed"
                    else "reflection_graph_node.retry_scheduled",
                    error_code=error_code,
                ),
                created_at=now,
                connection=connection,
            )

    async def renew_lease(
        self,
        task: ReflectionNodeTask,
        lease: TaskLease,
    ) -> ReflectionNodeTask | None:
        return await self.runtime.reflection_graph_nodes.renew_lease(
            task.task_id,
            worker_id=lease.lease_owner,
            now_utc=self.runtime.clock(),
            lease_seconds=self.runtime.settings.lease_seconds,
            attempt_count=lease.attempt_count,
            lease_generation=lease.lease_generation,
        )


__all__ = ["ReflectionGraphTaskStore"]
