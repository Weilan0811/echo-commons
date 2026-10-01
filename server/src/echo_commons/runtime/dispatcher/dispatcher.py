"""Generic recover/claim/route/execute loop for durable tasks."""

from __future__ import annotations

import asyncio
import logging
from collections.abc import Callable
from datetime import datetime

from echo_server.observability.logging import get_logger, log_event
from echo_server.runtime.dispatcher.contracts import (
    PersistentTaskStore,
    TaskClaimScope,
    TaskDisposition,
    TaskExecutionResult,
)
from echo_server.runtime.dispatcher.registry import TaskHandlerRegistry

logger = get_logger("dispatcher")


class TaskDispatcher:
    """Dispatch one durable task without knowing its business meaning."""

    def __init__(
        self,
        store: PersistentTaskStore,
        registry: TaskHandlerRegistry,
        *,
        worker_id: str,
        clock: Callable[[], datetime],
    ) -> None:
        self.store = store
        self.registry = registry
        self.worker_id = worker_id
        self.clock = clock

    async def recover_expired(self) -> int:
        """Recover expired leases through the persistent task port."""

        return await self.store.recover_expired(self.clock())

    async def dispatch_once(self, *, scope: TaskClaimScope | None = None) -> bool:
        """Claim and execute at most one task; return whether work was claimed."""

        lease = await self.store.claim_next(
            worker_id=self.worker_id,
            now_utc=self.clock(),
            scope=scope,
        )
        if lease is None:
            return False

        log_event(
            logger,
            logging.INFO,
            "task.claimed",
            correlation_id=lease.correlation_id,
            task_id=lease.task_id,
            worker_id=self.worker_id,
            attempt_count=lease.attempt_count,
        )
        try:
            handler = self.registry.resolve(lease.task_kind)
        except LookupError:
            await self.store.reschedule(
                lease,
                error_code="task_handler_not_registered",
                terminal=True,
            )
            return True

        try:
            result = await handler.execute(lease)
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            error_code = getattr(exc, "code", None) or exc.__class__.__name__.lower()
            log_event(
                logger,
                logging.ERROR,
                "task.handler_failed",
                correlation_id=lease.correlation_id,
                task_id=lease.task_id,
                task_kind=lease.task_kind,
                worker_id=self.worker_id,
                error_code=error_code,
                error_type=exc.__class__.__name__,
            )
            await self.store.reschedule(lease, error_code=error_code)
            return True

        if not isinstance(result, TaskExecutionResult):
            raise TypeError("task handler must return TaskExecutionResult")
        if result.disposition is TaskDisposition.RETRY:
            await self.store.reschedule(
                lease,
                error_code=result.error_code or "handler_requested_retry",
            )
        elif result.disposition is TaskDisposition.TERMINAL_FAILURE:
            await self.store.reschedule(
                lease,
                error_code=result.error_code or "handler_terminal_failure",
                terminal=True,
            )
        return True


__all__ = ["TaskDispatcher"]
