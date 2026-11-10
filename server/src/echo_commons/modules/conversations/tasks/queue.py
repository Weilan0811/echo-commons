import asyncio
from datetime import datetime

from echo_commons.agents.contracts.recovery import (
    FailureCategory,
    RecoveryAction,
    TaskRecoveryDecision,
)
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import SchedulingLane, TaskLease
from echo_commons.execution.observations import ExecutionEventPayload, ExecutionObservation
from echo_commons.execution.recovery import QueuePolicy, decision
from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
from echo_commons.modules.conversations.tasks.recovery import ConversationRecovery
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.repository import SocialRepository


class ConversationQueue:
    def __init__(
        self,
        database: Database,
        repository: ConversationQueueRepository,
        social: SocialRepository,
        completion: TurnCompletion,
        policy: QueuePolicy,
        recovery: ConversationRecovery,
    ) -> None:
        self.recovery = recovery
        self.recorder = recovery.recorder
        self.database, self.repository = database, repository
        self.social, self.completion, self.policy = social, completion, policy
        self.scheduling = None

    def reconcile_in(self, connection, now):
        pass

    def candidates_in(self, connection, now):
        return tuple(
            self.repository.candidate(row) for row in self.repository.candidates(connection, now)
        )

    def occupancies_in(self, connection):
        return self.repository.occupancies(connection)

    def waiting_scopes_in(self, connection):
        return {
            (row["community_id"], row["character_id"]): SchedulingLane.EXCHANGE
            for row in connection.execute(
                "SELECT t.community_id,t.character_id FROM conversation_tasks t "
                "JOIN communities c USING(community_id) WHERE t.status IN ('pending','retry_wait') "
                "AND c.status='active' "
                "AND json_extract(t.snapshot_json,'$.memory.context_prepared')=0"
            )
        }

    def claim_in(self, connection, owner, now, *, task_id=None):
        allowed = (
            (lambda candidate: self.scheduling.allowed_in(connection, candidate))
            if self.scheduling
            else None
        )
        lease = self.repository.claim(
            connection, owner, now, self.policy.lease_seconds, task_id=task_id, allowed=allowed
        )
        if lease is not None:
            self.recorder.record(connection, lease, "claimed", ExecutionEventPayload(), now)
        return lease

    async def claim(self, owner: str, now: datetime) -> TaskLease | None:
        return await asyncio.to_thread(self._claim, owner, now)

    def _claim(self, owner: str, now: datetime) -> TaskLease | None:
        if not owner.strip():
            raise ValueError("Worker identity is required")
        with self.database.transaction() as connection:
            now = utc_now()
            return self.claim_in(connection, owner, now)

    async def renew(self, lease: TaskLease, now: datetime) -> bool:
        return await asyncio.to_thread(self._renew, lease, now)

    def _renew(self, lease: TaskLease, now: datetime) -> bool:
        with self.database.transaction() as connection:
            now = utc_now()
            return self.repository.renew(connection, lease, now, self.policy.lease_seconds)

    async def recover(self, now: datetime) -> int:
        return await asyncio.to_thread(self._recover, now)

    def _recover(self, now: datetime) -> int:
        with self.database.transaction() as connection:
            now = utc_now()
            rows = self.repository.expired(connection, now)
            for row in rows:
                lease = TaskLease(
                    row["task_id"],
                    "conversation_reply",
                    row["attempt_count"],
                    row["lease_generation"],
                    row["lease_owner"],
                    now,
                    row["trace_id"],
                )
                self.recovery.apply(
                    connection,
                    lease,
                    decision("lease_expired", FailureCategory.LEASE, RecoveryAction.RETRY_TASK),
                    now,
                    expired=True,
                )
            return len(rows)

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
