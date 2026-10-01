import asyncio
from datetime import datetime, timedelta
from uuid import uuid4

from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.recovery import QueuePolicy
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.observability.outbox import enqueue_trace
from echo_commons.modules.conversations.repositories.queue import ConversationQueueRepository
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
    ) -> None:
        self.database, self.repository = database, repository
        self.social, self.completion, self.policy = social, completion, policy

    async def claim(self, owner: str, now: datetime) -> TaskLease | None:
        return await asyncio.to_thread(self._claim, owner, now)

    def _claim(self, owner: str, now: datetime) -> TaskLease | None:
        if not owner.strip():
            raise ValueError("Worker identity is required")
        with self.database.transaction() as connection:
            lease = self.repository.claim(connection, owner, now, self.policy.lease_seconds)
            if lease is not None:
                enqueue_trace(
                    connection,
                    str(uuid4()),
                    lease.trace_id,
                    "task.claimed",
                    "task",
                    lease.task_id,
                    {"attempt": lease.attempt, "generation": lease.generation},
                    now,
                )
            return lease

    async def renew(self, lease: TaskLease, now: datetime) -> bool:
        return await asyncio.to_thread(self._renew, lease, now)

    def _renew(self, lease: TaskLease, now: datetime) -> bool:
        with self.database.transaction() as connection:
            return self.repository.renew(connection, lease, now, self.policy.lease_seconds)

    async def recover(self, now: datetime) -> int:
        return await asyncio.to_thread(self._recover, now)

    def _recover(self, now: datetime) -> int:
        with self.database.transaction() as connection:
            rows = self.repository.expired(connection, now)
            for row in rows:
                failed = row["attempt_count"] >= self.policy.max_attempts
                self.repository.release(
                    connection,
                    row["task_id"],
                    "failed" if failed else "retry_wait",
                    now,
                    now,
                    "lease_expired",
                )
                enqueue_trace(
                    connection,
                    str(uuid4()),
                    row["trace_id"],
                    "task.failed" if failed else "task.recovered",
                    "task",
                    row["task_id"],
                    {"error_code": "lease_expired", "attempt": row["attempt_count"]},
                    now,
                )
                if failed:
                    self.social.complete_participation(
                        connection,
                        row["social_turn_id"],
                        row["character_id"],
                        "failed",
                        "failed",
                        now,
                    )
                    self.completion.update(connection, row["social_turn_id"], now)
            return len(rows)

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
        self, lease: TaskLease, now: datetime, code: str, terminal: bool, retry_after: float | None
    ) -> bool:
        with self.database.transaction() as connection:
            row = self.repository.owned(connection, lease, now)
            if row is None:
                return False
            failed = terminal or lease.attempt >= self.policy.max_attempts
            delay = max(
                self.policy.retry_backoff_seconds * 2 ** (lease.attempt - 1), retry_after or 0
            )
            available_at = now if failed else now + timedelta(seconds=delay)
            self.repository.release(
                connection,
                lease.task_id,
                "failed" if failed else "retry_wait",
                now,
                available_at,
                code,
            )
            enqueue_trace(
                connection,
                str(uuid4()),
                lease.trace_id,
                "task.failed" if failed else "task.retry_scheduled",
                "task",
                lease.task_id,
                {"error_code": code, "attempt": lease.attempt},
                now,
            )
            if failed:
                self.social.complete_participation(
                    connection, row["social_turn_id"], row["character_id"], "failed", "failed", now
                )
                self.completion.update(connection, row["social_turn_id"], now)
            return True
