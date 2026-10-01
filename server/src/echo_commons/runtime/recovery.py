from __future__ import annotations

from echo_server.agents.contracts import (
    AgentRunResult,
    AgentRunStatus,
    AgentStopReason,
    FailureCategory,
    FailureInfo,
    RecoveryAction,
    TaskRecoveryDecision,
)
from echo_server.runtime.proposals.reviewer import ReviewCode

_REPAIRABLE_REVIEW_CODES = {
    ReviewCode.THOUGHT_TOO_LONG: "请缩短 thought，使其符合长度限制。",
    ReviewCode.EMPTY_UTTERANCE: "请生成非空的 utterance 字段。",
    ReviewCode.UTTERANCE_TOO_LONG: "请缩短 utterance，使其符合长度限制。",
}

_DEFERRED_REVIEW_CODES = {
    ReviewCode.TASK_NOT_PROCESSING,
    ReviewCode.LEASE_NOT_OWNED,
    ReviewCode.LEASE_EXPIRED,
    ReviewCode.CONTEXT_EXPIRED,
}


def decide_review(code: ReviewCode | str) -> TaskRecoveryDecision:
    """根据一次确定性的提案审核结果选择任务处理方式。"""

    review_code = _review_code(code)
    code_value = review_code.value if review_code is not None else str(code)
    if review_code in _REPAIRABLE_REVIEW_CODES:
        failure = FailureInfo(
            code=code_value,
            category=FailureCategory.REVIEW,
            action=RecoveryAction.RETRY_TASK,
            retryable=True,
            repair_hint=_REPAIRABLE_REVIEW_CODES[review_code],
        )
        return TaskRecoveryDecision(action=failure.action, failure=failure)
    if review_code in _DEFERRED_REVIEW_CODES:
        failure = FailureInfo(
            code=code_value,
            category=FailureCategory.LEASE
            if review_code is not ReviewCode.CONTEXT_EXPIRED
            else FailureCategory.SOURCE,
            action=RecoveryAction.DEFER,
        )
        return TaskRecoveryDecision(action=failure.action, failure=failure)
    if review_code is ReviewCode.PROPOSAL_ALREADY_PROCESSED:
        failure = FailureInfo(
            code=code_value,
            category=FailureCategory.REVIEW,
            action=RecoveryAction.IGNORE,
        )
        return TaskRecoveryDecision(action=failure.action, failure=failure)
    failure = FailureInfo(
        code=code_value,
        category=FailureCategory.REVIEW,
        action=RecoveryAction.FAIL,
    )
    return TaskRecoveryDecision(action=failure.action, failure=failure)


def decide_agent_run(result: AgentRunResult) -> TaskRecoveryDecision | None:
    """根据一次 Agent Run 结果选择任务处理方式。"""

    if result.recovery is not None:
        return TaskRecoveryDecision(action=result.recovery.action, failure=result.recovery)
    if result.status in {AgentRunStatus.COMPLETED, AgentRunStatus.NO_PROPOSAL}:
        return None
    if result.status is AgentRunStatus.SUSPENDED:
        return _decision(
            code="agent_suspended",
            category=FailureCategory.HARNESS,
            action=RecoveryAction.DEFER,
        )
    if result.status is AgentRunStatus.CANCELLED:
        return _decision(
            code="agent_cancelled",
            category=FailureCategory.HARNESS,
            action=RecoveryAction.IGNORE,
        )
    if result.stop_reason in {
        AgentStopReason.DEADLINE_EXCEEDED,
        AgentStopReason.MODEL_ERROR,
    }:
        return _decision(
            code=_result_code(result),
            category=(
                FailureCategory.DEADLINE
                if result.stop_reason is AgentStopReason.DEADLINE_EXCEEDED
                else FailureCategory.PROVIDER
            ),
            action=RecoveryAction.RETRY_TASK,
            retryable=True,
        )
    if result.stop_reason is AgentStopReason.INVALID_MODEL_OUTPUT:
        return _decision(
            code=_result_code(result),
            category=FailureCategory.MODEL_OUTPUT,
            action=RecoveryAction.FAIL,
        )
    if result.stop_reason is AgentStopReason.BUDGET_EXHAUSTED:
        return _decision(
            code=_result_code(result),
            category=FailureCategory.BUDGET,
            action=RecoveryAction.FAIL,
        )
    if result.stop_reason is AgentStopReason.TOOL_NOT_ALLOWED:
        return _decision(
            code=_result_code(result),
            category=FailureCategory.CONFIGURATION,
            action=RecoveryAction.FAIL,
        )
    if result.stop_reason is AgentStopReason.TOOL_ERROR:
        return _decision(
            code=_result_code(result),
            category=FailureCategory.TOOL,
            action=RecoveryAction.FAIL,
        )
    return _decision(
        code=_result_code(result),
        category=FailureCategory.HARNESS,
        action=RecoveryAction.FAIL,
    )


def _decision(
    *,
    code: str,
    category: FailureCategory,
    action: RecoveryAction,
    retryable: bool = False,
    retry_after_seconds: float | None = None,
) -> TaskRecoveryDecision:
    failure = FailureInfo(
        code=code,
        category=category,
        action=action,
        retryable=retryable,
        retry_after_seconds=retry_after_seconds,
    )
    return TaskRecoveryDecision(action=action, failure=failure)


def _result_code(result: AgentRunResult) -> str:
    if result.diagnostic_codes:
        return result.diagnostic_codes[-1]
    return result.stop_reason.value


def _review_code(code: ReviewCode | str) -> ReviewCode | None:
    if isinstance(code, ReviewCode):
        return code
    try:
        return ReviewCode(code)
    except ValueError:
        return None


__all__ = ["decide_agent_run", "decide_review"]
