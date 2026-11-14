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
        result = await with_heartbeat(
            self.queue, lease, self._execute(lease), self.heartbeat_seconds
        )
        if result and lease.task_kind == "activity_turn":
            await self.commit.expressions.complete_turn(result["result_id"])
        return ExecutionOutcome(Disposition.HANDLED)

    async def _execute(self, lease: TaskLease) -> dict | None:
        artifact = await self.execution.execute(lease)
        return await asyncio.to_thread(self.commit.commit, lease, artifact)
