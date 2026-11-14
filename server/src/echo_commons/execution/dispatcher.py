import asyncio
import logging

from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import Disposition, TaskQueue
from echo_commons.execution.lease import LeaseLostError
from echo_commons.execution.observations import ExecutionObservation
from echo_commons.execution.registry import TaskRegistry
from echo_commons.execution.scheduling import scheduling_context

logger = logging.getLogger("echo_commons.execution")


class TaskDispatcher:
    def __init__(self, queue: TaskQueue, registry: TaskRegistry, owner: str) -> None:
        self.queue, self.registry, self.owner = queue, registry, owner
        self.active_task_id: str | None = None

    async def dispatch_once(self) -> bool:
        lease = await self.queue.claim(self.owner, utc_now())
        if lease is None:
            return False
        self.active_task_id = lease.task_id
        try:
            with scheduling_context(
                lease.scheduling_lane or self.registry.lanes.get(lease.task_kind)
            ):
                return await self._execute(lease)
        finally:
            self.active_task_id = None

    async def _execute(self, lease) -> bool:
        try:
            handler = self.registry.resolve(lease.task_kind)
            outcome = await handler.execute(lease)
        except asyncio.CancelledError:
            raise
        except LeaseLostError:
            await asyncio.to_thread(self.queue.recorder.ignored, lease, utc_now())
            return True
        except Exception as error:
            logger.exception(
                "Task execution failed",
                extra={"task_id": lease.task_id, "error_type": type(error).__name__},
            )
            await self.queue.apply_recovery(
                lease,
                utc_now(),
                self.registry.classify(lease.task_kind, error),
                ExecutionObservation(exception_type=type(error).__name__),
            )
            return True
        if outcome.disposition is Disposition.RECOVERY_REQUIRED:
            if outcome.recovery is None:
                raise ValueError("Recovery outcome requires a decision")
            await self.queue.apply_recovery(lease, utc_now(), outcome.recovery, outcome.observation)
        return True
