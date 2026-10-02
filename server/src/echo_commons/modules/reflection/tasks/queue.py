import asyncio
import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4

from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.recovery import QueuePolicy
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.infrastructure.observability.outbox import enqueue_trace
from echo_commons.modules.reflection.domain.graph import ReflectionGraphRun
from echo_commons.modules.reflection.domain.node import ReflectionNodeTask, ReflectionNodeTaskStatus
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.dependencies import bind_ready_inputs


class ReflectionQueue:
    def available(self, connection: sqlite3.Connection, run: ReflectionGraphRun) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM character_instances i JOIN communities c "
                "ON c.community_id = i.community_id WHERE i.character_id = ? "
                "AND i.community_id = ? AND i.availability_status = 'available' "
                "AND c.status = 'active'",
                (run.character_id, run.community_id),
            ).fetchone()
            is not None
        )

    def __init__(
        self,
        database: Database,
        nodes: NodeRepository,
        runs: RunRepository,
        policy: QueuePolicy,
    ) -> None:
        self.database, self.nodes, self.runs, self.policy = database, nodes, runs, policy
        self.artifacts = ArtifactRepository()

    def run_for(
        self, connection: sqlite3.Connection, node: ReflectionNodeTask
    ) -> ReflectionGraphRun:
        scope = self.runs.scope(connection, str(node.graph_run_id))
        return self.runs.get(
            connection, scope.community_id, scope.character_id, str(node.graph_run_id)
        )

    async def claim(self, owner: str, now: datetime) -> TaskLease | None:
        return await asyncio.to_thread(self._claim, owner, now)

    def _claim(self, owner: str, now: datetime) -> TaskLease | None:
        if not owner.strip():
            raise ValueError("Worker identity is required")
        with self.database.transaction() as connection:
            row = connection.execute(
                "SELECT n.node_task_id FROM reflection_node_tasks n "
                "JOIN reflection_graph_runs r ON r.graph_run_id = n.graph_run_id "
                "JOIN communities c ON c.community_id = r.community_id "
                "JOIN character_instances i ON i.character_id = r.character_id "
                "WHERE n.status IN ('pending','retry_wait') AND n.activated = 1 "
                "AND n.available_at_utc <= ? AND r.status IN ('pending','running','retry_wait') "
                "AND c.status = 'active' AND i.availability_status = 'available' "
                "AND NOT EXISTS (SELECT 1 FROM json_each(n.dependency_keys_json) dep "
                "LEFT JOIN reflection_node_tasks p ON p.graph_run_id = n.graph_run_id "
                "AND p.node_key = dep.value WHERE p.node_task_id IS NULL "
                "OR p.status NOT IN ('completed','skipped','failed')) "
                "ORDER BY n.available_at_utc, n.created_at_utc, n.node_task_id LIMIT 1",
                (utc_text(now),),
            ).fetchone()
            if row is None:
                return None
            node = self.nodes.get(connection, row[0])
            run = self.run_for(connection, node)
            graph_nodes = self.nodes.for_graph(connection, str(run.graph_run_id))
            if run.status in ("pending", "retry_wait"):
                run = run.start(now_utc=now)
                self.runs.save(connection, run)
            claimed = node.claim(
                worker_id=owner,
                now_utc=now,
                lease_until_utc=now + timedelta(seconds=self.policy.lease_seconds),
                completed_node_keys={
                    item.node_key for item in graph_nodes if item.status == "completed"
                },
                resolved_node_keys={
                    item.node_key for item in graph_nodes if item.status in ("skipped", "failed")
                },
            )
            self.nodes.save(connection, claimed)
            if run.trace_id is None:
                raise ValueError("Reflection run requires a trace identity")
            lease = TaskLease(
                str(claimed.task_id),
                "reflection",
                claimed.attempt_count,
                claimed.lease_generation,
                owner,
                claimed.lease_until_utc,
                str(run.trace_id),
            )
            self._trace(connection, claimed, run, "task.claimed", now)
            return lease

    def owned(self, connection: sqlite3.Connection, lease: TaskLease, now: datetime) -> bool:
        node = self.nodes.get(connection, lease.task_id)
        return lease.task_kind == "reflection" and node.has_valid_lease(
            worker_id=lease.owner,
            now_utc=now,
            attempt_count=lease.attempt,
            lease_generation=lease.generation,
        )

    async def renew(self, lease: TaskLease, now: datetime) -> bool:
        return await asyncio.to_thread(self._renew, lease, now)

    def _renew(self, lease: TaskLease, now: datetime) -> bool:
        with self.database.transaction() as connection:
            if not self.owned(connection, lease, now):
                return False
            node = self.nodes.get(connection, lease.task_id)
            run = self.run_for(connection, node)
            if run.is_terminal or not self.available(connection, run):
                return False
            node = node.renew_lease(
                worker_id=lease.owner,
                now_utc=now,
                lease_until_utc=now + timedelta(seconds=self.policy.lease_seconds),
                attempt_count=lease.attempt,
                lease_generation=lease.generation,
            )
            self.nodes.save(connection, node)
            return True

    async def recover(self, now: datetime) -> int:
        return await asyncio.to_thread(self._recover, now)

    def _recover(self, now: datetime) -> int:
        with self.database.transaction() as connection:
            identifiers = tuple(
                row[0]
                for row in connection.execute(
                    "SELECT node_task_id FROM reflection_node_tasks "
                    "WHERE status = 'processing' AND lease_until_utc <= ?",
                    (utc_text(now),),
                )
            )
            for identifier in identifiers:
                node = self.nodes.get(connection, identifier)
                run = self.run_for(connection, node)
                if run.is_terminal:
                    node = node.cancel(now_utc=now, reason_code="graph_terminal")
                else:
                    node = node.recover_expired(now_utc=now, max_attempts=self.policy.max_attempts)
                self.nodes.save(connection, node)
                self._trace(
                    connection,
                    node,
                    run,
                    "task.failed" if node.status == "failed" else "task.recovered",
                    now,
                )
                self._fail_required(connection, node, run, now)
            return len(identifiers)

    async def reschedule(
        self,
        lease: TaskLease,
        now: datetime,
        *,
        error_code: str,
        terminal: bool,
        retry_after_seconds: float | None = None,
    ) -> bool:
        return await asyncio.to_thread(
            self._reschedule, lease, now, error_code, terminal, retry_after_seconds
        )

    def _reschedule(
        self,
        lease: TaskLease,
        now: datetime,
        error_code: str,
        terminal: bool,
        retry_after_seconds: float | None,
    ) -> bool:
        with self.database.transaction() as connection:
            if not self.owned(connection, lease, now):
                return False
            node = self.nodes.get(connection, lease.task_id)
            run = self.run_for(connection, node)
            delay = max(
                self.policy.retry_backoff_seconds * 2 ** (lease.attempt - 1),
                retry_after_seconds or 0,
            )
            node = node.retry_or_fail(
                worker_id=lease.owner,
                now_utc=now,
                available_at_utc=now + timedelta(seconds=delay),
                error_code=error_code,
                max_attempts=self.policy.max_attempts,
                terminal=terminal,
                attempt_count=lease.attempt,
                lease_generation=lease.generation,
            )
            self.nodes.save(connection, node)
            self._trace(
                connection,
                node,
                run,
                "task.failed" if node.status == "failed" else "task.retry_scheduled",
                now,
            )
            self._fail_required(connection, node, run, now)
            return True

    def _fail_required(
        self,
        connection: sqlite3.Connection,
        node: ReflectionNodeTask,
        run: ReflectionGraphRun,
        now: datetime,
    ) -> None:
        if (
            node.status is not ReflectionNodeTaskStatus.FAILED
            or run.is_terminal
        ):
            return
        if node.node_key not in run.required_node_keys:
            bind_ready_inputs(
                connection, str(run.graph_run_id), now, self.runs, self.nodes, self.artifacts
            )
            return
        run = run.fail(now_utc=now, error_code=node.last_error_code)
        self.runs.save(connection, run)
        for other in self.nodes.for_graph(connection, str(run.graph_run_id)):
            if not other.is_terminal:
                self.nodes.save(
                    connection, other.cancel(now_utc=now, reason_code="required_node_failed")
                )
        self._trace(connection, node, run, "reflection.graph.failed", now)

    def _trace(
        self,
        connection: sqlite3.Connection,
        node: ReflectionNodeTask,
        run: ReflectionGraphRun,
        kind: str,
        now: datetime,
    ) -> None:
        enqueue_trace(
            connection,
            str(uuid4()),
            str(run.trace_id),
            kind,
            "reflection_node",
            str(node.task_id),
            {
                "graph_run_id": str(run.graph_run_id),
                "attempt": node.attempt_count,
                "generation": node.lease_generation,
                "error_code": node.last_error_code,
            },
            now,
        )
