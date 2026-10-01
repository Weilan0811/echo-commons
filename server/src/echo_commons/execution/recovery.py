from dataclasses import dataclass

from echo_commons.agents.contracts.run import AgentRunResult, AgentRunStatus
from echo_commons.execution.contracts import Disposition, ExecutionOutcome


@dataclass(frozen=True, slots=True)
class QueuePolicy:
    lease_seconds: float = 90
    max_attempts: int = 3
    retry_backoff_seconds: float = 1

    def __post_init__(self) -> None:
        if self.lease_seconds <= 0 or self.max_attempts < 1 or self.retry_backoff_seconds < 0:
            raise ValueError("Queue limits are invalid")


def decide_run(result: AgentRunResult) -> ExecutionOutcome:
    if result.status in (AgentRunStatus.COMPLETED, AgentRunStatus.NO_PROPOSAL):
        return ExecutionOutcome(Disposition.COMPLETED)
    if result.status is AgentRunStatus.RETRYABLE:
        return ExecutionOutcome(
            Disposition.RETRY,
            result.recovery.code if result.recovery else result.stop_reason.value,
            result.recovery.retry_after_seconds if result.recovery else None,
        )
    return ExecutionOutcome(
        Disposition.FAILED, result.recovery.code if result.recovery else result.stop_reason.value
    )
