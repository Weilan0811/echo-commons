import asyncio
import logging

from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import Disposition, TaskQueue
from echo_commons.execution.lease import LeaseLostError
from echo_commons.execution.registry import TaskRegistry
from echo_commons.infrastructure.database.errors import StorageError

logger = logging.getLogger("echo_commons.execution")


class TaskDispatcher:
    def __init__(self, queue: TaskQueue, registry: TaskRegistry, owner: str) -> None:
        self.queue, self.registry, self.owner = queue, registry, owner

    async def dispatch_once(self) -> bool:
        lease = await self.queue.claim(self.owner, utc_now())
        if lease is None:
            return False
        try:
            handler = self.registry.resolve(lease.task_kind)
            outcome = await handler.execute(lease)
        except asyncio.CancelledError:
            raise
        except LeaseLostError:
            return True
        except StorageError as error:
            logger.exception("Task storage failed: %s", lease.task_id)
            await self.queue.reschedule(
                lease, utc_now(), error_code=error.code, terminal=not error.retryable
            )
            return True
        except Exception as error:
            logger.exception("Task failed: %s, kind: %s", lease.task_id, lease.task_kind)
            await self.queue.reschedule(
                lease, utc_now(), error_code=type(error).__name__, terminal=True
            )
            return True
        if outcome.disposition in (Disposition.RETRY, Disposition.FAILED):
            await self.queue.reschedule(
                lease,
                utc_now(),
                error_code=outcome.error_code or "execution_failed",
                terminal=outcome.disposition is Disposition.FAILED,
                retry_after_seconds=outcome.retry_after_seconds,
            )
        return True
