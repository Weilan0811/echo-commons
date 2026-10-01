import asyncio
import logging
from contextlib import suppress
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from echo_commons.execution.clock import utc_now

logger = logging.getLogger("echo_commons.workers")


class Worker(Protocol):
    async def run_once(self) -> bool: ...


@dataclass
class WorkerState:
    name: str
    status: str = "stopped"
    last_success_utc: datetime | None = None
    last_error_type: str | None = None
    failure_count: int = 0


class Supervisor:
    def __init__(
        self, workers: dict[str, Worker], *, poll_seconds: float, shutdown_seconds: float
    ) -> None:
        self.workers, self.poll_seconds, self.shutdown_seconds = (
            workers,
            poll_seconds,
            shutdown_seconds,
        )
        self.states = {name: WorkerState(name) for name in workers}
        self._stop = asyncio.Event()
        self._tasks: list[asyncio.Task] = []

    async def start(self) -> None:
        if self._tasks:
            raise RuntimeError("Workers are already running")
        self._stop.clear()
        self._tasks = [
            asyncio.create_task(self._run(name, worker), name=name)
            for name, worker in self.workers.items()
        ]

    async def _run(self, name: str, worker: Worker) -> None:
        state = self.states[name]
        try:
            while not self._stop.is_set():
                state.status = "running"
                try:
                    worked = await worker.run_once()
                except asyncio.CancelledError:
                    raise
                except Exception as error:
                    state.status = "failed"
                    state.last_error_type = type(error).__name__
                    state.failure_count += 1
                    logger.exception("Worker failed: %s", name)
                    worked = False
                else:
                    state.last_success_utc = utc_now()
                    state.last_error_type = None
                if not worked:
                    with suppress(TimeoutError):
                        await asyncio.wait_for(self._stop.wait(), timeout=self.poll_seconds)
        finally:
            state.status = "stopped"

    async def close(self) -> None:
        self._stop.set()
        if self._tasks:
            _, pending = await asyncio.wait(self._tasks, timeout=self.shutdown_seconds)
            for task in pending:
                task.cancel()
            await asyncio.gather(*self._tasks, return_exceptions=True)
            self._tasks.clear()
