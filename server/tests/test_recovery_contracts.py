from __future__ import annotations

from uuid import uuid4

import pytest
from pydantic import ValidationError

from echo_server.agents.contracts import (
    AgentRunResult,
    AgentRunStatus,
    AgentStopReason,
    FailureCategory,
    FailureInfo,
    RecoveryAction,
    TaskRecoveryDecision,
)


def test_failure_info_keeps_a_stable_recovery_shape():
    failure = FailureInfo(
        code="empty_utterance",
        category=FailureCategory.REVIEW,
        action=RecoveryAction.RETRY_TASK,
        retryable=True,
        repair_hint="请生成非空的 utterance 字段。",
    )

    decision = TaskRecoveryDecision(action=failure.action, failure=failure)

    assert decision.action is RecoveryAction.RETRY_TASK
    assert decision.failure.code == "empty_utterance"
    assert decision.failure.retry_after_seconds is None


def test_non_retry_actions_cannot_be_marked_retryable():
    with pytest.raises(ValidationError):
        FailureInfo(
            code="provider_not_configured",
            category=FailureCategory.CONFIGURATION,
            action=RecoveryAction.FAIL,
            retryable=True,
        )


def test_repair_hint_requires_a_recovery_action_that_can_use_it():
    with pytest.raises(ValidationError):
        FailureInfo(
            code="invalid_payload",
            category=FailureCategory.REVIEW,
            action=RecoveryAction.FAIL,
            repair_hint="请修正输出。",
        )


def test_recovery_decision_action_matches_failure():
    failure = FailureInfo(
        code="fatal_error",
        category=FailureCategory.HARNESS,
        action=RecoveryAction.FAIL,
    )

    with pytest.raises(ValidationError):
        TaskRecoveryDecision(action=RecoveryAction.RETRY_TASK, failure=failure)


def test_successful_agent_run_cannot_contain_recovery_information():
    recovery = FailureInfo(
        code="provider_timeout",
        category=FailureCategory.PROVIDER,
        action=RecoveryAction.RETRY_TASK,
        retryable=True,
    )

    with pytest.raises(ValidationError):
        AgentRunResult(
            invocation_id=uuid4(),
            agent_id="xiaojin.character",
            agent_kind="character",
            harness_version="harness-v4",
            model_profile="light",
            status=AgentRunStatus.NO_PROPOSAL,
            stop_reason=AgentStopReason.NO_MOTIVATION,
            recovery=recovery,
        )


def test_retry_after_seconds_must_be_non_negative():
    with pytest.raises(ValidationError):
        FailureInfo(
            code="timeout",
            category=FailureCategory.PROVIDER,
            action=RecoveryAction.RETRY_TASK,
            retryable=True,
            retry_after_seconds=-1,
        )
