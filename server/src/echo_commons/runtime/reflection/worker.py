"""Independent background worker for Reflection tasks."""

from __future__ import annotations

import asyncio
import logging
from contextlib import suppress
from datetime import datetime

from echo_server.config import Settings
from echo_server.observability.logging import get_logger, log_event
from echo_server.runtime.dispatcher import TaskClaimScope
from echo_server.runtime.modules import ReflectionModule

logger = get_logger("reflection-worker")


class ReflectionWorker:
    """Poll the Reflection queue independently from conversation replies."""

    def __init__(self, runtime: ReflectionModule, settings: Settings | None = None) -> None:
        self.runtime = runtime
        self.settings = settings or runtime.settings
        self._wake = asyncio.Event()
        self._stop = asyncio.Event()
        self._task: asyncio.Task[None] | None = None
        self._failure: BaseException | None = None
        self._last_successful_loop_at: datetime | None = None
        self.runtime.reflection_wakeup = self._wake

    @property
    def task(self) -> asyncio.Task[None] | None:
        return self._task

    @property
    def failure(self) -> BaseException | None:
        return self._failure

    @property
    def last_successful_loop_at(self) -> datetime | None:
        return self._last_successful_loop_at

    async def run_once(self) -> bool:
        if self._stop.is_set() or not self.runtime.accepting_work:
            return False
        flushed = await self.runtime.flush_trace_outbox(
            max_items=self.settings.trace_batch_size,
            worker_id=self.runtime.reflection_worker_id,
        )
        graph_dispatched = await self.runtime.reflection_graph_dispatcher.dispatch_once(
            scope=TaskClaimScope(account_id=self.settings.account_id)
        )
        await self.runtime.flush_trace_outbox(
            max_items=self.settings.trace_batch_size,
            worker_id=self.runtime.reflection_worker_id,
        )
        return graph_dispatched or flushed > 0

    async def start(self) -> None:
        if self._task is None or self._task.done():
            self._stop.clear()
            self._failure = None
            self._last_successful_loop_at = None
            self._task = asyncio.create_task(self._run(), name="echo-reflection-worker")
            log_event(
                logger,
                logging.INFO,
                "reflection_worker.started",
                worker_id=self.runtime.reflection_worker_id,
            )

    async def stop(self, timeout: float = 5.0) -> None:
        self._stop.set()
        self._wake.set()
        if self._task is not None:
            try:
                await asyncio.wait_for(self._task, timeout=timeout)
            except TimeoutError:
                self._task.cancel()
                await asyncio.gather(self._task, return_exceptions=True)
            finally:
                self._task = None
        log_event(
            logger,
            logging.INFO,
            "reflection_worker.stopped",
            worker_id=self.runtime.reflection_worker_id,
        )

    async def _run(self) -> None:
        try:
            while not self._stop.is_set():
                did_work = await self.run_once()
                self._last_successful_loop_at = self.runtime.clock()
                if did_work:
                    continue
                self._wake.clear()
                with suppress(TimeoutError):
                    await asyncio.wait_for(
                        self._wake.wait(), timeout=self.settings.worker_poll_interval_seconds
                    )
        except asyncio.CancelledError:
            raise
        except Exception as exc:
            self._failure = exc
            log_event(
                logger,
                logging.ERROR,
                "reflection_worker.failed",
                worker_id=self.runtime.reflection_worker_id,
                error_code=getattr(exc, "code", None) or exc.__class__.__name__.lower(),
                error_type=exc.__class__.__name__,
            )


__all__ = ["ReflectionWorker"]
