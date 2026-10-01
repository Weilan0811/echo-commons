import asyncio
from collections.abc import Awaitable
from typing import TypeVar

from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import TaskLease, TaskQueue

T = TypeVar("T")


class LeaseLostError(RuntimeError):
    code = "lease_lost"


async def with_heartbeat(
    queue: TaskQueue, lease: TaskLease, operation: Awaitable[T], interval_seconds: float
) -> T:
    if interval_seconds <= 0:
        raise ValueError("Heartbeat interval must be positive")

    async def heartbeat() -> None:
        while True:
            await asyncio.sleep(interval_seconds)
            if not await queue.renew(lease, utc_now()):
                raise LeaseLostError("Task lease is no longer owned")

    execution = asyncio.ensure_future(operation)
    renewal = asyncio.create_task(heartbeat())
    try:
        finished, _ = await asyncio.wait((execution, renewal), return_when=asyncio.FIRST_COMPLETED)
        if renewal in finished:
            await renewal
        return await execution
    finally:
        for task in (execution, renewal):
            if not task.done():
                task.cancel()
        await asyncio.gather(execution, renewal, return_exceptions=True)
