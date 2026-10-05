from __future__ import annotations

from echo_commons.agents.contracts.recovery import FailureCategory, FailureInfo, RecoveryAction
from echo_commons.infrastructure.models.protocol import ModelGatewayError

_REPAIRABLE_OUTPUT_CODES = frozenset(
    {
        "invalid_model_output",
        "output_truncated",
    }
)

_REPAIRABLE_TOOL_CODES = frozenset(
    {
        "invalid_query",
        "query_too_long",
        "invalid_limit",
    }
)

_RETRYABLE_TOOL_CODES = frozenset(
    {
        "memory_source_changed",
        "memory_search_failed",
        "tool_error",
        "tool_execution_error",
    }
)

_FATAL_TOOL_CODES = frozenset(
    {
        "memory_search_not_authorized",
        "tool_not_allowed",
        "tool_budget_exhausted",
        "model_step_budget_exhausted",
        "model_request_budget_exhausted",
    }
)

_REPAIR_HINTS = {
    "invalid_model_output": "请只返回符合输出 Contract 的 JSON 对象，并补全所有必需字段。",
    "output_truncated": "请完整返回输出 Contract 要求的 JSON 对象。",
    "invalid_query": "请把 memory_search 的 query 改为非空字符串。",
    "query_too_long": "请缩短 memory_search 的 query。",
    "invalid_limit": "请把 memory_search 的 limit 改为 1 到 5 之间的整数。",
}


def classify_model_output_error(code: str, *, repair_allowed: bool = True) -> FailureInfo:
    """分类一次模型输出问题，不保留 Provider 原文。"""

    if repair_allowed and code in _REPAIRABLE_OUTPUT_CODES:
        return FailureInfo(
            code=code,
            category=FailureCategory.MODEL_OUTPUT,
            action=RecoveryAction.REPAIR,
            retryable=True,
            repair_hint=_REPAIR_HINTS[code],
        )
    return FailureInfo(
        code=code,
        category=FailureCategory.MODEL_OUTPUT,
        action=RecoveryAction.FAIL,
    )


def classify_gateway_error(error: ModelGatewayError) -> FailureInfo:
    """把 Gateway 重试用尽后的 Provider 错误转换成统一失败信息。"""

    configuration_error = error.code in {
        "authentication",
        "quota_exceeded",
        "invalid_request",
        "provider_not_configured",
        "model_configuration_invalid",
    }
    category = FailureCategory.CONFIGURATION if configuration_error else FailureCategory.PROVIDER
    retryable = error.retryable and not configuration_error
    action = RecoveryAction.RETRY_TASK if retryable else RecoveryAction.FAIL
    return FailureInfo(
        code=error.code,
        category=category,
        action=action,
        retryable=retryable,
        retry_after_seconds=error.retry_after_seconds if retryable else None,
    )


def classify_tool_error(code: str, *, repair_allowed: bool = True) -> FailureInfo:
    """为 Harness 循环分类一次只读工具结果。"""

    if repair_allowed and code in _REPAIRABLE_TOOL_CODES:
        return FailureInfo(
            code=code,
            category=FailureCategory.TOOL,
            action=RecoveryAction.REPAIR,
            retryable=True,
            repair_hint=_REPAIR_HINTS[code],
        )
    if code == "memory_source_changed":
        return FailureInfo(
            code=code,
            category=FailureCategory.SOURCE,
            action=RecoveryAction.RETRY_TASK,
            retryable=True,
        )
    if code in _RETRYABLE_TOOL_CODES:
        return FailureInfo(
            code=code,
            category=FailureCategory.TOOL,
            action=RecoveryAction.RETRY_TASK,
            retryable=True,
        )
    if code in _FATAL_TOOL_CODES:
        category = (
            FailureCategory.BUDGET
            if "budget" in code
            else FailureCategory.CONFIGURATION
            if code == "memory_search_not_authorized"
            else FailureCategory.TOOL
        )
        return FailureInfo(
            code=code,
            category=category,
            action=RecoveryAction.FAIL,
        )
    return FailureInfo(
        code=code,
        category=FailureCategory.TOOL,
        action=RecoveryAction.FAIL,
    )


def repair_hint_for(code: str) -> str | None:
    """返回已知可修正错误码对应的固定提示。"""

    return _REPAIR_HINTS.get(code)


__all__ = [
    "classify_gateway_error",
    "classify_model_output_error",
    "classify_tool_error",
    "repair_hint_for",
]
