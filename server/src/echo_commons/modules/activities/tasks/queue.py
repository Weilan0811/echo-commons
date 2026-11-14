import asyncio
from datetime import datetime, timedelta

from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.observations import ExecutionEventPayload
from echo_commons.execution.recovery import QueuePolicy, decision
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.activities.lifecycle import ActivityLifecycle
from echo_commons.modules.activities.repositories.tasks import ActivityTasks
from echo_commons.modules.activities.tasks.recovery import ActivityRecovery


class ActivityQueue:
    def __init__(
        self,
        database: Database,
        tasks: ActivityTasks,
        recovery: ActivityRecovery,
        policy: QueuePolicy,
        lifecycle: ActivityLifecycle,
    ) -> None:
        self.database, self.repository, self.recovery, self.policy, self.lifecycle = (
            database,
            tasks,
            recovery,
            policy,
            lifecycle,
        )
        self.recorder = recovery.recorder
        self.scheduling = None

    def reconcile_in(self, connection, now):
        self.lifecycle.reconcile_in(connection, now)

    def candidates_in(self, connection, now):
        return tuple(
            self.repository.candidate(row) for row in self.repository.candidates(connection, now)
        )

    def occupancies_in(self, connection):
        return self.repository.occupancies(connection)

    def waiting_scopes_in(self, connection):
        return self.repository.waiting_scopes(connection)

    async def claim(self, owner: str, now: datetime) -> TaskLease | None:
        return await asyncio.to_thread(self._claim, owner)

    def _claim(self, owner):
        if not owner.strip():
            raise ValueError("Worker identity is required")
        with self.database.transaction() as connection:
            now = utc_now()
            self.lifecycle.reconcile_in(connection, now)
            return self.claim_in(connection, owner, now)

    def claim_in(self, connection, owner, now, *, task_id=None):
        allowed = (
            (lambda candidate: self.scheduling.allowed_in(connection, candidate))
            if self.scheduling
            else None
        )
        lease = self.repository.claim(
            connection, owner, now, self.policy.lease_seconds, task_id=task_id, allowed=allowed
        )
        if lease:
            self.recorder.record(connection, lease, "claimed", ExecutionEventPayload(), now)
        return lease

    async def renew(self, lease: TaskLease, now: datetime) -> bool:
        return await asyncio.to_thread(self._renew, lease)

    def _renew(self, lease):
        with self.database.transaction() as connection:
            now = utc_now()
            self.lifecycle.reconcile_in(connection, now)
            if self.repository.owned(connection, lease, now) is None:
                return False
            connection.execute(
                f"UPDATE {self.repository.table} SET lease_until_utc=? WHERE task_id=?",
                (utc_text(now + timedelta(seconds=self.policy.lease_seconds)), lease.task_id),
            )
            return True

    async def recover(self, now: datetime) -> int:
        return await asyncio.to_thread(self._recover)

    def _recover(self):
        with self.database.transaction() as connection:
            now = utc_now()
            self.lifecycle.reconcile_in(connection, now)
            rows = connection.execute(
                f"SELECT * FROM {self.repository.table} "
                "WHERE status='processing' AND lease_until_utc<=?",
                (utc_text(now),),
            ).fetchall()
            for row in rows:
                lease = TaskLease(
                    row["task_id"],
                    self.repository.kind(row),
                    row["attempt_count"],
                    row["lease_generation"],
                    row["lease_owner"],
                    now,
                    self.repository.get(connection, row["task_id"])["trace_id"],
                )
                self.recovery.apply(
                    connection,
                    lease,
                    decision("lease_expired", FailureCategory.LEASE, RecoveryAction.RETRY_TASK),
                    now,
                    expired=True,
                )
            return len(rows)

    async def apply_recovery(self, lease, now, recovery, observation=None):
        return await asyncio.to_thread(self._apply, lease, recovery, observation)

    def _apply(self, lease, recovery, observation):
        with self.database.transaction() as connection:
            return self.recovery.apply(
                connection, lease, recovery, utc_now(), observation=observation
            )
