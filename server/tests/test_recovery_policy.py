from __future__ import annotations

from uuid import uuid4

import pytest

from echo_server.agents.contracts import (
    AgentRunResult,
    AgentRunStatus,
    AgentStopReason,
    FailureCategory,
    FailureInfo,
    RecoveryAction,
)
from echo_server.agents.harness.recovery import (
    classify_gateway_error,
    classify_model_output_error,
    classify_tool_error,
)
from echo_server.runtime.proposals.reviewer import ReviewCode
from echo_server.runtime.recovery import decide_agent_run, decide_review
from echo_server.services.model_gateway.protocol import ModelGatewayError


def test_gateway_retryable_error_becomes_a_task_retry():
    failure = classify_gateway_error(
        ModelGatewayError(
            code="rate_limited",
            retryable=True,
            retry_after_seconds=2.5,
        )
    )

    assert failure.category is FailureCategory.PROVIDER
    assert failure.action is RecoveryAction.RETRY_TASK
    assert failure.retryable is True
    assert failure.retry_after_seconds == 2.5


def test_gateway_configuration_error_does_not_retry():
    failure = classify_gateway_error(ModelGatewayError(code="provider_not_configured"))

    assert failure.category is FailureCategory.CONFIGURATION
    assert failure.action is RecoveryAction.FAIL
    assert failure.retryable is False


@pytest.mark.parametrize(
    ("code", "action"),
    [
        ("invalid_model_output", RecoveryAction.REPAIR),
        ("invalid_json", RecoveryAction.REPAIR),
        ("missing_utterance", RecoveryAction.REPAIR),
        ("output_truncated", RecoveryAction.REPAIR),
    ],
)
def test_model_output_errors_have_a_bounded_repair_path(code: str, action: RecoveryAction):
    failure = classify_model_output_error(code)

    assert failure.action is action
    assert failure.retryable is True
    assert failure.repair_hint is not None
    assert "异常" not in failure.repair_hint


def test_repeated_model_output_error_becomes_terminal():
    failure = classify_model_output_error("invalid_json", repair_allowed=False)

    assert failure.action is RecoveryAction.FAIL
    assert failure.retryable is False
    assert failure.repair_hint is None


@pytest.mark.parametrize(
    ("code", "action", "category"),
    [
        ("invalid_query", RecoveryAction.REPAIR, FailureCategory.TOOL),
        ("memory_source_changed", RecoveryAction.RETRY_TASK, FailureCategory.SOURCE),
        ("memory_search_failed", RecoveryAction.RETRY_TASK, FailureCategory.TOOL),
        ("memory_search_not_authorized", RecoveryAction.FAIL, FailureCategory.CONFIGURATION),
        ("tool_budget_exhausted", RecoveryAction.FAIL, FailureCategory.BUDGET),
        ("unregistered_tool_error", RecoveryAction.FAIL, FailureCategory.TOOL),
    ],
)
def test_tool_error_mapping(code: str, action: RecoveryAction, category: FailureCategory):
    failure = classify_tool_error(code)

    assert failure.action is action
    assert failure.category is category


@pytest.mark.parametrize(
    ("code", "action"),
    [
        (ReviewCode.THOUGHT_TOO_LONG, RecoveryAction.RETRY_TASK),
        (ReviewCode.EMPTY_UTTERANCE, RecoveryAction.RETRY_TASK),
        (ReviewCode.UTTERANCE_TOO_LONG, RecoveryAction.RETRY_TASK),
        (ReviewCode.CONTEXT_EXPIRED, RecoveryAction.DEFER),
        (ReviewCode.LEASE_EXPIRED, RecoveryAction.DEFER),
        (ReviewCode.PROPOSAL_ALREADY_PROCESSED, RecoveryAction.IGNORE),
        (ReviewCode.CHARACTER_MISMATCH, RecoveryAction.FAIL),
        (ReviewCode.INVALID_PAYLOAD, RecoveryAction.FAIL),
    ],
)
def test_review_error_mapping(code: ReviewCode, action: RecoveryAction):
    decision = decide_review(code)

    assert decision.action is action
    assert decision.failure.code == code.value
    if action is RecoveryAction.RETRY_TASK:
        assert decision.failure.repair_hint is not None


def test_unknown_review_code_fails_without_retry():
    decision = decide_review("new_review_code")

    assert decision.action is RecoveryAction.FAIL
    assert decision.failure.code == "new_review_code"
    assert decision.failure.retryable is False


def test_agent_run_status_uses_stop_reason_until_harness_supplies_recovery():
    deadline = decide_agent_run(_run(AgentRunStatus.RETRYABLE, AgentStopReason.DEADLINE_EXCEEDED))
    budget = decide_agent_run(_run(AgentRunStatus.RETRYABLE, AgentStopReason.BUDGET_EXHAUSTED))
    tool = decide_agent_run(_run(AgentRunStatus.FAILED, AgentStopReason.TOOL_ERROR))
    completed = decide_agent_run(_run(AgentRunStatus.NO_PROPOSAL, AgentStopReason.NO_MOTIVATION))

    assert deadline is not None
    assert deadline.action is RecoveryAction.RETRY_TASK
    assert budget is not None
    assert budget.action is RecoveryAction.FAIL
    assert tool is not None
    assert tool.action is RecoveryAction.FAIL
    assert tool.failure.category is FailureCategory.TOOL
    assert completed is None


def test_agent_run_recovery_field_takes_precedence():
    recovery = FailureInfo(
        code="memory_source_changed",
        category=FailureCategory.SOURCE,
        action=RecoveryAction.RETRY_TASK,
        retryable=True,
    )
    decision = decide_agent_run(
        _run(
            AgentRunStatus.FAILED,
            AgentStopReason.HARNESS_ERROR,
            recovery=recovery,
        )
    )

    assert decision is not None
    assert decision.action is RecoveryAction.RETRY_TASK
    assert decision.failure.code == "memory_source_changed"


def _run(
    status: AgentRunStatus,
    stop_reason: AgentStopReason,
    *,
    recovery: FailureInfo | None = None,
) -> AgentRunResult:
    return AgentRunResult(
        invocation_id=uuid4(),
        agent_id="xiaojin.character",
        agent_kind="character",
        harness_version="harness-v4",
        model_profile="light",
        status=status,
        stop_reason=stop_reason,
        recovery=recovery,
    )
