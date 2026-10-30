import asyncio

from echo_commons.execution.contracts import Disposition, ExecutionOutcome, TaskLease
from echo_commons.execution.lease import with_heartbeat
from echo_commons.modules.activities.tasks.commit import ActivityCommit
from echo_commons.modules.activities.tasks.execution import ActivityExecution
from echo_commons.modules.activities.tasks.queue import ActivityQueue


class ActivityHandler:
    def __init__(
        self,
        execution: ActivityExecution,
        commit: ActivityCommit,
        queue: ActivityQueue,
        heartbeat_seconds: float,
    ) -> None:
        self.execution, self.commit, self.queue, self.heartbeat_seconds = (
            execution,
            commit,
            queue,
            heartbeat_seconds,
        )

    async def execute(self, lease: TaskLease) -> ExecutionOutcome:
        return await with_heartbeat(self.queue, lease, self._execute(lease), self.heartbeat_seconds)

    async def _execute(self, lease: TaskLease) -> ExecutionOutcome:
        artifact = await self.execution.execute(lease)
        await asyncio.to_thread(self.commit.commit, lease, artifact)
        return ExecutionOutcome(Disposition.HANDLED)
