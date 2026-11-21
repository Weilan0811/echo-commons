import asyncio
from datetime import timedelta

from echo_commons.agents.harness.prompt import read_prompt_resource
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import Disposition, ExecutionOutcome, TaskLease
from echo_commons.execution.lease import with_heartbeat
from echo_commons.execution.recovery import decide_run
from echo_commons.modules.conversations.tasks.commit import ConversationCommit
from echo_commons.modules.conversations.tasks.execution import ConversationExecution
from echo_commons.modules.conversations.tasks.queue import ConversationQueue
from echo_commons.modules.social.scoring import WillingnessJudgments


class ConversationHandler:
    def __init__(
        self,
        execution: ConversationExecution,
        commit: ConversationCommit,
        queue: ConversationQueue,
        heartbeat_seconds: float,
        safety_margin_seconds: float = 0,
        participation: WillingnessJudgments | None = None,
    ) -> None:
        self.execution, self.commit, self.queue = execution, commit, queue
        self.heartbeat_seconds = heartbeat_seconds
        self.safety_margin_seconds = safety_margin_seconds
        self.participation = participation

    async def execute(self, lease: TaskLease) -> ExecutionOutcome:
        return await with_heartbeat(self.queue, lease, self._execute(lease), self.heartbeat_seconds)

    async def _execute(self, lease: TaskLease) -> ExecutionOutcome:
        prepared = await asyncio.to_thread(
            self.execution.prepare,
            lease.task_id,
            attempt=lease.attempt,
            deadline_utc=lease.expires_at_utc - timedelta(seconds=self.safety_margin_seconds),
        )
        await asyncio.to_thread(self.queue.recorder.started, lease, prepared.invocation, utc_now())
        selected = self.participation is not None and await asyncio.to_thread(
            self.participation.expression_selected, lease.task_id
        )
        invocation = prepared.invocation
        if selected:
            invocation = invocation.model_copy(
                update={
                    "execution_policy": invocation.execution_policy.model_copy(
                        update={
                            "output_instructions": invocation.execution_policy.output_instructions
                            + "\n"
                            + read_prompt_resource("conversation/expression.md"),
                        }
                    ),
                }
            )
        result = await prepared.agent.run(invocation)
        await asyncio.to_thread(self.queue.recorder.finished, lease, result, utc_now())
        recovery = decide_run(result)
        if recovery is not None:
            return ExecutionOutcome(
                Disposition.RECOVERY_REQUIRED, recovery, self.queue.recorder.observation(result)
            )
        receipt = await asyncio.to_thread(self.commit.commit, lease, invocation, result)
        return receipt.outcome
