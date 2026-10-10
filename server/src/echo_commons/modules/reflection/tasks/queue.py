import asyncio
import sqlite3
from datetime import datetime, timedelta

from echo_commons.agents.contracts.recovery import (
    FailureCategory,
    RecoveryAction,
    TaskRecoveryDecision,
)
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.errors import ExecutionDeferred
from echo_commons.execution.observations import ExecutionEventPayload, ExecutionObservation
from echo_commons.execution.recovery import QueuePolicy, decision
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.reflection.domain.graph import ReflectionGraphRun
from echo_commons.modules.reflection.domain.node import ReflectionNodeTask
from echo_commons.modules.reflection.repositories.artifacts import ArtifactRepository
from echo_commons.modules.reflection.repositories.nodes import NodeRepository
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.recovery import ReflectionRecovery


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
        recovery: ReflectionRecovery,
    ) -> None:
        self.recovery = recovery
        self.recorder = recovery.recorder
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
            now = utc_now()
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
                run.execution_generation,
            )
            self.recorder.record(connection, lease, "claimed", ExecutionEventPayload(), now)
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
            now = utc_now()
            if not self.owned(connection, lease, now):
                return False
            node = self.nodes.get(connection, lease.task_id)
            run = self.run_for(connection, node)
            if run.is_terminal:
                return False
            if not self.available(connection, run):
                raise ExecutionDeferred()
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
            now = utc_now()
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
                lease = TaskLease(
                    str(node.task_id),
                    "reflection",
                    node.attempt_count,
                    node.lease_generation,
                    node.lease_owner,
                    now,
                    str(run.trace_id),
                    run.execution_generation,
                )
                if run.is_terminal:
                    self.nodes.save(
                        connection, node.cancel(now_utc=now, reason_code="graph_terminal")
                    )
                    self.recorder.record(
                        connection,
                        lease,
                        "result_ignored",
                        ExecutionEventPayload(reason_code="graph_terminal"),
                        now,
                    )
                else:
                    self.recovery.apply(
                        connection,
                        lease,
                        decision("lease_expired", FailureCategory.LEASE, RecoveryAction.RETRY_TASK),
                        now,
                        expired=True,
                    )
            return len(identifiers)

    async def apply_recovery(
        self,
        lease: TaskLease,
        now: datetime,
        recovery: TaskRecoveryDecision,
        observation: ExecutionObservation | None = None,
    ):
        return await asyncio.to_thread(self._apply_recovery, lease, now, recovery, observation)

    def _apply_recovery(
        self,
        lease: TaskLease,
        now: datetime,
        recovery: TaskRecoveryDecision,
        observation: ExecutionObservation | None = None,
    ):
        with self.database.transaction() as connection:
            now = utc_now()
            return self.recovery.apply(connection, lease, recovery, now, observation=observation)
