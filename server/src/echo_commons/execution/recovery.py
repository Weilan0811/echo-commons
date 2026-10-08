from dataclasses import dataclass
from datetime import datetime, timedelta
from random import uniform

from pydantic import BaseModel, ConfigDict

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.recovery import (
    FailureCategory,
    FailureInfo,
    RecoveryAction,
    TaskRecoveryDecision,
)
from echo_commons.agents.contracts.run import AgentRunResult, AgentRunStatus
from echo_commons.agents.harness.context import repair_instruction
from echo_commons.agents.harness.recovery import classify_gateway_error
from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.infrastructure.models.errors import classify_configuration_error
from echo_commons.infrastructure.models.protocol import ModelGatewayError
from echo_commons.infrastructure.models.registry import ModelConfigurationError


@dataclass(frozen=True, slots=True)
class QueuePolicy:
    lease_seconds: float = 90
    max_attempts: int = 3
    retry_backoff_seconds: float = 1

    def __post_init__(self) -> None:
        if self.lease_seconds <= 0 or self.max_attempts < 1 or self.retry_backoff_seconds < 0:
            raise ValueError("Queue limits are invalid")


class AppliedRecovery(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    decision: TaskRecoveryDecision
    action: RecoveryAction
    task_state: str
    retry_exhausted: bool = False
    effective_wait_seconds: float | None = None
    next_attempt_at_utc: datetime | None = None


def decision(
    code: str,
    category: FailureCategory,
    action: RecoveryAction = RecoveryAction.FAIL,
    *,
    hint: str | None = None,
    wait: float | None = None,
) -> TaskRecoveryDecision:
    failure = FailureInfo(
        code=code,
        category=category,
        action=action,
        retryable=action in (RecoveryAction.REPAIR, RecoveryAction.RETRY_TASK),
        repair_hint=hint,
        retry_after_seconds=wait,
    )
    return TaskRecoveryDecision(action=action, failure=failure)


class RecoveryPolicy:
    def __init__(self, limits: QueuePolicy) -> None:
        self.limits = limits

    @staticmethod
    def classify(error: Exception) -> TaskRecoveryDecision:
        if isinstance(error, ExecutionError):
            return decision(error.code, error.category, error.action)
        if isinstance(error, ModelConfigurationError):
            error = classify_configuration_error(error)
        if isinstance(error, ModelGatewayError):
            failure = classify_gateway_error(error)
            return TaskRecoveryDecision(action=failure.action, failure=failure)
        if isinstance(error, StorageError):
            return decision(
                error.code,
                FailureCategory.PERSISTENCE,
                RecoveryAction.RETRY_TASK if error.retryable else RecoveryAction.FAIL,
            )
        return decision("execution_unexpected_error", FailureCategory.HARNESS)

    def plan(
        self,
        recovery: TaskRecoveryDecision,
        attempt: int,
        now: datetime,
        *,
        retry_delays: tuple[float, ...] | None = None,
    ) -> AppliedRecovery:
        if recovery.action is RecoveryAction.REPAIR:
            recovery = decision("agent_run_state_invalid", FailureCategory.HARNESS)
        max_attempts = (
            len(retry_delays) + 1 if retry_delays is not None else self.limits.max_attempts
        )
        exhausted = recovery.action is RecoveryAction.RETRY_TASK and attempt >= max_attempts
        action = RecoveryAction.FAIL if exhausted else recovery.action
        waiting = action in (RecoveryAction.RETRY_TASK, RecoveryAction.DEFER)
        backoff = (
            retry_delays[attempt - 1] + uniform(0, retry_delays[attempt - 1] * 0.1)
            if retry_delays is not None and waiting
            else self.limits.retry_backoff_seconds * 2 ** max(0, attempt - 1)
        )
        delay = (
            max(
                backoff,
                recovery.failure.retry_after_seconds or 0,
            )
            if waiting
            else None
        )
        return AppliedRecovery(
            decision=recovery,
            action=action,
            retry_exhausted=exhausted,
            task_state="retry_wait"
            if waiting
            else "failed"
            if action is RecoveryAction.FAIL
            else "ignored",
            effective_wait_seconds=delay,
            next_attempt_at_utc=now + timedelta(seconds=delay) if delay is not None else None,
        )

    @staticmethod
    def hint(applied: AppliedRecovery | None) -> str | None:
        if (
            applied is None
            or applied.action is not RecoveryAction.RETRY_TASK
            or applied.decision.failure.category is not FailureCategory.REVIEW
        ):
            return None
        failure = applied.decision.failure
        return (
            repair_instruction(failure.code, failure.repair_hint) if failure.repair_hint else None
        )


def decide_run(result: AgentRunResult) -> TaskRecoveryDecision | None:
    if result.status in (AgentRunStatus.COMPLETED, AgentRunStatus.NO_PROPOSAL):
        return None
    if result.recovery is not None:
        return TaskRecoveryDecision(action=result.recovery.action, failure=result.recovery)
    if result.status is AgentRunStatus.SUSPENDED:
        return decision("agent_suspended", FailureCategory.SOURCE, RecoveryAction.DEFER)
    if result.status is AgentRunStatus.CANCELLED:
        return decision("agent_cancelled", FailureCategory.LEASE, RecoveryAction.IGNORE)
    code = result.diagnostic_codes[0] if result.diagnostic_codes else result.stop_reason.value
    return decision(code, FailureCategory.HARNESS)
