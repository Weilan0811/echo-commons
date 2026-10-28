import asyncio
from datetime import timedelta

from echo_commons.agents.contracts.run import (
    AgentRunResult,
    AgentRunStatus,
    AgentStep,
    AgentStopReason,
)
from echo_commons.agents.harness.prompt import read_prompt_resource
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import Disposition, ExecutionOutcome, TaskLease
from echo_commons.execution.lease import with_heartbeat
from echo_commons.execution.recovery import decide_run
from echo_commons.modules.conversations.tasks.commit import ConversationCommit
from echo_commons.modules.conversations.tasks.execution import ConversationExecution
from echo_commons.modules.conversations.tasks.queue import ConversationQueue
from echo_commons.modules.social.judgment import SocialParticipation


class ConversationHandler:
    def __init__(
        self,
        execution: ConversationExecution,
        commit: ConversationCommit,
        queue: ConversationQueue,
        heartbeat_seconds: float,
        safety_margin_seconds: float = 0,
        participation: SocialParticipation | None = None,
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
        verdict = (
            await self.participation.evaluate(lease, prepared.invocation.context)
            if self.participation is not None
            else None
        )
        invocation = prepared.invocation
        if verdict and verdict.choice == "participate":
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
        if verdict and verdict.choice == "silent":
            result = AgentRunResult(
                invocation_id=invocation.identity.invocation_id,
                agent_id=invocation.identity.agent_id,
                agent_kind=invocation.identity.agent_kind,
                model_profile=invocation.execution_policy.model_profile,
                status=AgentRunStatus.NO_PROPOSAL,
                stop_reason=AgentStopReason.NO_MOTIVATION,
            )
        else:
            result = await prepared.agent.run(invocation)
        if verdict and verdict.choice != "ordinary":
            result = result.model_copy(
                update={
                    "usage_summary": verdict.usage.add(result.usage_summary),
                    "steps": (
                        AgentStep(
                            step_index=1,
                            response_kind="participation",
                            usage_summary=verdict.usage,
                            duration_ms=verdict.duration_ms,
                            diagnostic_codes=(
                                f"participation:{verdict.choice}",
                                f"model_profile:{verdict.model_profile}",
                                f"reused:{verdict.reused}",
                            ),
                        ),
                        *(
                            step.model_copy(update={"step_index": step.step_index + 1})
                            for step in result.steps
                        ),
                    ),
                }
            )
        await asyncio.to_thread(self.queue.recorder.finished, lease, result, utc_now())
        recovery = decide_run(result)
        if recovery is not None:
            return ExecutionOutcome(
                Disposition.RECOVERY_REQUIRED, recovery, self.queue.recorder.observation(result)
            )
        receipt = await asyncio.to_thread(self.commit.commit, lease, invocation, result)
        return receipt.outcome
