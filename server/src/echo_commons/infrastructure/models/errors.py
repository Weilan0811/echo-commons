from __future__ import annotations

from echo_commons.infrastructure.models.protocol import ModelGatewayError
from echo_commons.infrastructure.models.registry import ModelConfigurationError


def classify_configuration_error(error: ModelConfigurationError) -> ModelGatewayError:
    """把模型配置错误转换成不可重试的 Gateway 错误。"""

    return ModelGatewayError(
        code=error.code,
        retryable=False,
        provider_attempt=0,
    )


def classify_provider_error(
    exc: Exception,
    *,
    provider_attempt: int = 1,
) -> ModelGatewayError:
    """把 SDK 或网络错误转换成稳定且脱敏的 Gateway 错误。"""

    status_code = getattr(exc, "status_code", None)
    if not isinstance(status_code, int):
        status_code = None
    name = exc.__class__.__name__
    if name in {"APITimeoutError", "ConnectTimeout", "ReadTimeout", "WriteTimeout"}:
        code, retryable = "timeout", True
    elif name == "RateLimitError" or status_code == 429:
        code, retryable = "rate_limited", True
    elif name in {"AuthenticationError", "PermissionDeniedError"} or status_code in {401, 403}:
        code, retryable = "authentication", False
    elif status_code in {402, 413}:
        code, retryable = "quota_exceeded", False
    elif (
        name in {"APIConnectionError", "InternalServerError"}
        or status_code in {408, 409, 425}
        or (status_code is not None and status_code >= 500)
    ):
        code, retryable = "temporary_unavailable", True
    elif status_code in {400, 404, 422} or name in {
        "BadRequestError",
        "NotFoundError",
        "UnprocessableEntityError",
    }:
        code, retryable = "invalid_request", False
    else:
        code, retryable = "unknown", False
    return ModelGatewayError(
        code=code,
        retryable=retryable,
        status_code=status_code,
        provider_attempt=provider_attempt,
        retry_after_seconds=_retry_after_seconds(exc) if retryable else None,
    )


def _retry_after_seconds(exc: Exception) -> float | None:
    response = getattr(exc, "response", None)
    headers = getattr(response, "headers", None)
    if headers is None:
        return None
    raw = headers.get("retry-after") or headers.get("Retry-After")
    try:
        value = float(raw)
    except (TypeError, ValueError):
        return None
    return value if value >= 0 else None


__all__ = ["classify_configuration_error", "classify_provider_error"]
