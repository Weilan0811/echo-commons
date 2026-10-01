from __future__ import annotations

from enum import StrEnum

from pydantic import BaseModel, ConfigDict, Field, model_validator


class FailureCategory(StrEnum):
    """负责分类某类失败的系统边界。"""

    PROVIDER = "provider"
    MODEL_OUTPUT = "model_output"
    TOOL = "tool"
    SOURCE = "source"
    REVIEW = "review"
    BUDGET = "budget"
    DEADLINE = "deadline"
    LEASE = "lease"
    PERSISTENCE = "persistence"
    CONFIGURATION = "configuration"
    HARNESS = "harness"


class RecoveryAction(StrEnum):
    """失败的 Agent 操作下一步要执行的动作。"""

    REPAIR = "repair"
    RETRY_TASK = "retry_task"
    DEFER = "defer"
    FAIL = "fail"
    IGNORE = "ignore"


class FailureInfo(BaseModel):
    """供 Runtime 选择恢复动作的、与 Provider 无关的失败信息。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    code: str = Field(min_length=1, max_length=120)
    category: FailureCategory
    action: RecoveryAction
    retryable: bool = False
    retry_after_seconds: float | None = Field(default=None, ge=0)
    repair_hint: str | None = Field(default=None, min_length=1, max_length=500)

    @model_validator(mode="after")
    def validate_recovery_fields(self) -> FailureInfo:
        if self.action in {RecoveryAction.REPAIR, RecoveryAction.RETRY_TASK}:
            if not self.retryable:
                raise ValueError("repair and task retry failures must be retryable")
        elif self.retryable:
            raise ValueError("deferred, failed, and ignored failures are not retryable")
        if self.repair_hint is not None and self.action not in {
            RecoveryAction.REPAIR,
            RecoveryAction.RETRY_TASK,
        }:
            raise ValueError("repair_hint requires repair or task retry action")
        return self


class TaskRecoveryDecision(BaseModel):
    """Runtime 对一次 Agent 任务尝试结果作出的恢复决定。"""

    model_config = ConfigDict(extra="forbid", frozen=True)

    action: RecoveryAction
    failure: FailureInfo

    @model_validator(mode="after")
    def action_matches_failure(self) -> TaskRecoveryDecision:
        if self.action is not self.failure.action:
            raise ValueError("recovery decision action must match failure action")
        return self


__all__ = [
    "FailureCategory",
    "FailureInfo",
    "RecoveryAction",
    "TaskRecoveryDecision",
]
