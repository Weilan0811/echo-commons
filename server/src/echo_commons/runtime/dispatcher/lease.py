"""Conversation-task adapter for the generic persistent-task port."""

from __future__ import annotations

import asyncio
from collections.abc import Awaitable, Callable
from datetime import datetime, timedelta
from uuid import uuid4

from echo_server.domain.task import ConversationTask
from echo_server.observability.trace import safe_trace_payload
from echo_server.runtime.dispatcher.contracts import (
    PersistentTaskStore,
    TaskClaimScope,
    TaskLease,
)
from echo_server.runtime.errors import LeaseHeartbeatError, LeaseLostError
from echo_server.runtime.modules import ConversationModule

FailureScheduler = Callable[..., Awaitable[None]]


class LeaseHeartbeat:
    """Run a bounded lease renewal loop for one long-running operation."""

    def __init__(
        self,
        renew: Callable[[], Awaitable[object | None]],
        *,
        interval_seconds: float,
    ) -> None:
        self._renew = renew
        self._interval_seconds = interval_seconds

    async def run(self) -> None:
        if self._interval_seconds <= 0:
            raise LeaseHeartbeatError("lease heartbeat interval must be positive")
        while True:
            await asyncio.sleep(self._interval_seconds)
            try:
                renewed = await self._renew()
            except asyncio.CancelledError:
                raise
            except Exception as exc:
                raise LeaseHeartbeatError("task lease heartbeat failed") from exc
            if renewed is None:
                raise LeaseLostError("task lease is no longer owned")


class ConversationTaskStore(PersistentTaskStore):
    """Adapt the existing conversation_tasks table without adding a second queue."""

    task_kind = "conversation.reply"

    def __init__(
        self,
        runtime: ConversationModule,
        *,
        failure_scheduler: FailureScheduler | None = None,
    ) -> None:
        self.runtime = runtime
        self.failure_scheduler = failure_scheduler

    async def recover_expired(self, now_utc: datetime) -> int:
        await self.runtime.ensure_started()
        async with self.runtime.database.transaction(immediate=True) as connection:
            return await self.runtime.runtime_tasks.recover_expired(
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
        if worker_id != self.runtime.worker_id:
            raise ValueError("conversation task store is bound to its Runtime worker")
        account_id = (
            scope.account_id
            if scope is not None and scope.account_id is not None
            else self.runtime.settings.account_id
        )
        conversation_id = scope.scope_key if scope else None
        await self.runtime.ensure_started()
        async with self.runtime.database.transaction(immediate=True) as connection:
            task = await self.runtime.runtime_tasks.claim_next(
                account_id=account_id,
                conversation_id=conversation_id,
                worker_id=worker_id,
                now_utc=now_utc,
                lease_seconds=self.runtime.settings.lease_seconds,
                connection=connection,
            )
            if task is not None:
                await self.runtime.task_traces.enqueue(
                    trace_id=uuid4(),
                    correlation_id=task.trace_id,
                    kind="task.claimed",
                    entity_type="task",
                    entity_id=str(task.task_id),
                    payload=safe_trace_payload("task.claimed", attempt_count=task.attempt_count),
                    created_at=now_utc,
                    connection=connection,
                )
        if task is None:
            return None
        if task.lease_until_utc is None or task.lease_owner is None:
            raise RuntimeError("claimed conversation task has no lease")
        return TaskLease(
            task_id=task.task_id,
            task_kind=self.task_kind,
            correlation_id=task.trace_id,
            scope_key=task.conversation_id,
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
        if not isinstance(task, ConversationTask):
            raise TypeError("conversation task lease has an invalid payload")
        if self.failure_scheduler is not None and not terminal:
            await self.failure_scheduler(
                task.task_id,
                task.trace_id,
                error_code,
                attempt_count=lease.attempt_count,
                lease_generation=lease.lease_generation,
            )
            return

        await self._reschedule_direct(task, lease, error_code=error_code, terminal=terminal)

    async def _reschedule_direct(
        self,
        task: ConversationTask,
        lease: TaskLease,
        *,
        error_code: str,
        terminal: bool,
    ) -> None:
        now = self.runtime.clock()
        available_at = (
            now
            if terminal
            else now + timedelta(seconds=self.runtime.settings.retry_backoff_seconds)
        )
        async with self.runtime.database.transaction(immediate=True) as connection:
            current = await self.runtime.runtime_tasks.get(task.task_id, connection)
            if current is None or not current.has_valid_lease(
                worker_id=lease.lease_owner,
                now_utc=now,
                attempt_count=lease.attempt_count,
                lease_generation=lease.lease_generation,
            ):
                return
            await self.runtime.runtime_tasks.retry_or_fail(
                task.task_id,
                worker_id=lease.lease_owner,
                now_utc=now,
                available_at_utc=available_at,
                error_code=error_code,
                max_attempts=0 if terminal else self.runtime.settings.max_agent_attempts,
                attempt_count=lease.attempt_count,
                lease_generation=lease.lease_generation,
                connection=connection,
            )
            await self.runtime.task_traces.enqueue(
                trace_id=uuid4(),
                correlation_id=task.trace_id,
                kind="task.failed" if terminal else "task.retry_scheduled",
                entity_type="task",
                entity_id=str(task.task_id),
                payload=safe_trace_payload(
                    "task.failed" if terminal else "task.retry_scheduled",
                    error_code=error_code,
                ),
                created_at=now,
                connection=connection,
            )


__all__ = ["ConversationTaskStore", "LeaseHeartbeat"]
