import asyncio
from datetime import timedelta

from echo_commons.execution.contracts import Disposition, ExecutionOutcome, TaskLease
from echo_commons.execution.lease import with_heartbeat
from echo_commons.execution.recovery import decide_run
from echo_commons.modules.conversations.tasks.commit import ConversationCommit
from echo_commons.modules.conversations.tasks.execution import ConversationExecution
from echo_commons.modules.conversations.tasks.queue import ConversationQueue


class ConversationHandler:
    def __init__(
        self,
        execution: ConversationExecution,
        commit: ConversationCommit,
        queue: ConversationQueue,
        heartbeat_seconds: float,
        safety_margin_seconds: float = 0,
    ) -> None:
        self.execution, self.commit, self.queue = execution, commit, queue
        self.heartbeat_seconds = heartbeat_seconds
        self.safety_margin_seconds = safety_margin_seconds

    async def execute(self, lease: TaskLease) -> ExecutionOutcome:
        return await with_heartbeat(self.queue, lease, self._execute(lease), self.heartbeat_seconds)

    async def _execute(self, lease: TaskLease) -> ExecutionOutcome:
        prepared = await asyncio.to_thread(
            self.execution.prepare,
            lease.task_id,
            attempt=lease.attempt,
            deadline_utc=lease.expires_at_utc - timedelta(seconds=self.safety_margin_seconds),
        )
        result = await prepared.agent.run(prepared.invocation)
        outcome = decide_run(result)
        if outcome.disposition is not Disposition.COMPLETED:
            return outcome
        receipt = await asyncio.to_thread(self.commit.commit, lease, prepared.invocation, result)
        return receipt.outcome
