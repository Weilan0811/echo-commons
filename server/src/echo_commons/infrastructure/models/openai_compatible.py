from __future__ import annotations

import asyncio
import inspect
import json
import logging
from collections.abc import Awaitable, Callable, Mapping
from datetime import UTC, datetime
from time import perf_counter

from openai import AsyncOpenAI

from echo_commons.agents.contracts.run import UsageSummary
from echo_commons.infrastructure.observability.debug_capture import AgentDebugCapture
from echo_commons.infrastructure.observability.logging import get_logger, log_event

from .errors import classify_configuration_error, classify_provider_error
from .metrics import ProviderUsageTracker
from .protocol import (
    BeforeModelRequest,
    ModelGatewayError,
    ModelRequest,
    ModelResponse,
    ModelResponseKind,
    PromptMessage,
    ToolCall,
)
from .registry import ModelConfigurationError, ModelEntry, ModelRegistry

logger = get_logger("model_gateway")


Sleep = Callable[[float], Awaitable[None]]
Clock = Callable[[], datetime]


class OpenAICompatibleGateway:
    """Route one provider-neutral request through the configured OpenAI endpoint."""

    def __init__(
        self,
        registry: ModelRegistry,
        *,
        sleep: Sleep = asyncio.sleep,
        clock: Clock | None = None,
        usage_tracker: ProviderUsageTracker | None = None,
        debug_capture: AgentDebugCapture | None = None,
    ) -> None:
        self.registry = registry
        self._sleep = sleep
        self._clock = clock or (lambda: datetime.now(UTC))
        self.usage_tracker = usage_tracker or ProviderUsageTracker()
        self.debug_capture = debug_capture
        self._clients: dict[str, AsyncOpenAI] = {}

    async def generate(
        self, request: ModelRequest, *, before_request: BeforeModelRequest | None = None
    ) -> ModelResponse:
        try:
            entry = self.registry.resolve(request.model_profile, request.model_entry_id)
        except ModelConfigurationError as exc:
            raise classify_configuration_error(exc) from exc
        api_key = self.registry.credential_for(entry)
        if api_key is None:
            raise ModelGatewayError(
                code="provider_not_configured",
                retryable=False,
                provider_attempt=0,
            )

        client = self._client_for(entry, api_key)
        max_attempts = (
            entry.max_retries
            if request.max_provider_retries is None
            else request.max_provider_retries
        ) + 1
        for provider_attempt in range(1, max_attempts + 1):
            if before_request is not None:
                await before_request()
            remaining = self._remaining_seconds(request.deadline_utc)
            if remaining is not None and remaining <= 0:
                raise ModelGatewayError(
                    code="timeout",
                    retryable=True,
                    provider_attempt=provider_attempt,
                )
            timeout = (
                min(entry.request_timeout_seconds, remaining)
                if remaining is not None
                else entry.request_timeout_seconds
            )
            call_started_at = perf_counter()
            provider_request = _request_params(entry, request)
            captured = False
            try:
                if self.debug_capture is not None:
                    try:
                        self.debug_capture.capture_model_started(
                            request,
                            entry,
                            provider_request=provider_request,
                            provider_attempt=provider_attempt,
                        )
                    except Exception as exc:
                        log_event(
                            logger,
                            logging.WARNING,
                            "agent.debug_capture.failed",
                            correlation_id=request.trace_id,
                            error_type=exc.__class__.__name__,
                        )
                log_event(
                    logger,
                    logging.INFO,
                    "model.call.started",
                    correlation_id=request.trace_id,
                    invocation_id=request.invocation_id,
                    agent_id=request.agent_id,
                    model_profile=request.model_profile,
                    provider=entry.model_vendor,
                    model=entry.model,
                    provider_attempt=provider_attempt,
                )
                raw_response, ttft_ms = await self._call_provider(
                    client,
                    entry,
                    request,
                    timeout,
                    call_started_at,
                    provider_request,
                    provider_attempt=provider_attempt,
                )
                try:
                    response = normalize_completion(
                        raw_response,
                        entry,
                        latency_ms=_duration_ms(call_started_at),
                        ttft_ms=ttft_ms,
                        provider_attempt=provider_attempt,
                    )
                except Exception as exc:
                    error = ModelGatewayError(
                        code="invalid_provider_response",
                        retryable=False,
                        provider_attempt=provider_attempt,
                    )
                    captured = self._capture_model_call(
                        request,
                        entry,
                        provider_request=provider_request,
                        raw_response=raw_response,
                        normalized_response=None,
                        provider_attempt=provider_attempt,
                        ttft_ms=ttft_ms,
                        error=exc,
                    )
                    self._log_failure(request, entry, error, provider_attempt, call_started_at)
                    raise error from exc
                self._capture_model_call(
                    request,
                    entry,
                    provider_request=provider_request,
                    raw_response=raw_response,
                    normalized_response=response,
                    provider_attempt=provider_attempt,
                    ttft_ms=ttft_ms,
                )
                aggregate = self.usage_tracker.record(entry.model_vendor, response.usage_summary)
                event = (
                    "model.call.invalid"
                    if response.kind is ModelResponseKind.INVALID
                    else "model.call.completed"
                )
                level = (
                    logging.WARNING if response.kind is ModelResponseKind.INVALID else logging.INFO
                )
                log_event(
                    logger,
                    level,
                    event,
                    correlation_id=request.trace_id,
                    provider=entry.model_vendor,
                    access_route=entry.access_route,
                    model_vendor=entry.model_vendor,
                    model=response.model,
                    model_profile=request.model_profile,
                    provider_attempt=provider_attempt,
                    request_id=response.request_id,
                    duration_ms=response.latency_ms,
                    ttft_ms=response.ttft_ms,
                    input_tokens=response.usage_summary.input_tokens,
                    cache_read_tokens=response.usage_summary.cache_read_tokens,
                    cache_write_tokens=response.usage_summary.cache_write_tokens,
                    output_tokens=response.usage_summary.output_tokens,
                    total_tokens=response.usage_summary.total_tokens,
                    cache_hit_ratio=response.usage_summary.cache_hit_ratio,
                    response_kind=response.kind.value,
                    error_code=response.error_code,
                    finish_reason=response.finish_reason,
                    provider_model_request_count=aggregate.model_request_count,
                    provider_cache_hit_ratio=aggregate.cache_hit_ratio,
                )
                return response
            except asyncio.CancelledError:
                raise
            except ModelGatewayError as exc:
                if not captured:
                    self._capture_model_call(
                        request,
                        entry,
                        provider_request=provider_request,
                        raw_response=None,
                        normalized_response=None,
                        provider_attempt=provider_attempt,
                        error=exc,
                    )
                if not exc.retryable or provider_attempt >= max_attempts:
                    self._log_failure(request, entry, exc, provider_attempt, call_started_at)
                    raise
                delay = _retry_delay(exc, entry, provider_attempt)
                remaining = self._remaining_seconds(request.deadline_utc)
                if remaining is not None and delay >= remaining:
                    self._log_failure(
                        request,
                        entry,
                        exc,
                        provider_attempt,
                        call_started_at,
                        retry_delay_seconds=delay,
                    )
                    raise
                log_event(
                    logger,
                    logging.WARNING,
                    "model.call.retry",
                    correlation_id=request.trace_id,
                    provider=entry.model_vendor,
                    access_route=entry.access_route,
                    model_vendor=entry.model_vendor,
                    model=entry.model,
                    model_profile=request.model_profile,
                    provider_attempt=provider_attempt,
                    error_code=exc.code,
                    retryable=exc.retryable,
                    retry_delay_seconds=delay,
                    duration_ms=_duration_ms(call_started_at),
                )
                await self._sleep(delay)

        raise AssertionError("model gateway retry loop exited unexpectedly")

    async def close(self) -> None:
        for client in self._clients.values():
            await client.close()
        self._clients.clear()

    def _client_for(self, entry: ModelEntry, api_key: str) -> AsyncOpenAI:
        client = self._clients.get(entry.entry_id)
        if client is None:
            client = _default_client_factory(entry, api_key)
            self._clients[entry.entry_id] = client
        return client

    async def _call_provider(
        self,
        client: AsyncOpenAI,
        entry: ModelEntry,
        request: ModelRequest,
        timeout: float,
        call_started_at: float,
        provider_request: dict[str, object],
        provider_attempt: int,
    ) -> tuple[object, int | None]:
        operation = client.chat.completions.create

        async def invoke() -> tuple[object, int | None]:
            result = operation(**provider_request)
            if inspect.isawaitable(result):
                result = await result
            if request.stream:
                return await _collect_stream(
                    result,
                    call_started_at,
                    provider_attempt=provider_attempt,
                )
            return result, None

        try:
            return await asyncio.wait_for(invoke(), timeout=timeout)
        except asyncio.CancelledError:
            raise
        except TimeoutError as exc:
            raise ModelGatewayError(
                code="timeout",
                retryable=True,
                provider_attempt=provider_attempt,
                exception_type=type(exc).__name__,
            ) from exc
        except ModelGatewayError:
            raise
        except Exception as exc:
            raise classify_provider_error(exc, provider_attempt=provider_attempt) from exc

    def _capture_model_call(
        self,
        request: ModelRequest,
        entry: ModelEntry,
        *,
        provider_request: dict[str, object],
        raw_response: object | None,
        normalized_response: ModelResponse | None,
        provider_attempt: int,
        ttft_ms: int | None = None,
        error: BaseException | None = None,
    ) -> bool:
        if self.debug_capture is None:
            return False
        try:
            self.debug_capture.capture_model_call(
                request,
                entry,
                provider_request=provider_request,
                raw_response=raw_response,
                normalized_response=normalized_response,
                provider_attempt=provider_attempt,
                ttft_ms=ttft_ms,
                error=error,
            )
        except Exception as exc:  # noqa: BLE001 - diagnostics must not break Agent execution.
            log_event(
                logger,
                logging.WARNING,
                "agent.debug_capture.failed",
                correlation_id=request.trace_id,
                error_type=exc.__class__.__name__,
            )
            return False
        return True

    def _remaining_seconds(self, deadline: datetime | None) -> float | None:
        if deadline is None:
            return None
        return (deadline - self._clock()).total_seconds()

    @staticmethod
    def _log_failure(
        request: ModelRequest,
        entry: ModelEntry,
        error: ModelGatewayError,
        provider_attempt: int,
        started_at: float,
        retry_delay_seconds: float | None = None,
    ) -> None:
        log_event(
            logger,
            logging.WARNING,
            "model.call.failed",
            correlation_id=request.trace_id,
            provider=entry.model_vendor,
            access_route=entry.access_route,
            model_vendor=entry.model_vendor,
            model=entry.model,
            model_profile=request.model_profile,
            provider_attempt=provider_attempt,
            error_code=error.code,
            status_code=error.status_code,
            exception_type=error.exception_type,
            request_id=error.request_id,
            retryable=error.retryable,
            retry_delay_seconds=retry_delay_seconds,
            duration_ms=_duration_ms(started_at),
        )


def _default_client_factory(entry: ModelEntry, api_key: str) -> AsyncOpenAI:
    return AsyncOpenAI(
        api_key=api_key,
        base_url=entry.base_url,
        timeout=entry.request_timeout_seconds,
        max_retries=0,
    )


def _request_params(entry: ModelEntry, request: ModelRequest) -> dict[str, object]:
    params: dict[str, object] = {
        "model": entry.model,
        "messages": [_prompt_message_payload(message) for message in request.messages],
        "stream": request.stream,
    }
    response_format = entry.response_format
    # 工具调用遵循供应商函数协议；最终内容由 Harness 按契约校验。
    if response_format and not request.tool_definitions:
        params["response_format"] = {"type": response_format}
    max_output_tokens = request.max_output_tokens or entry.max_output_tokens
    if max_output_tokens is not None:
        params["max_tokens"] = max_output_tokens
    temperature = request.temperature if request.temperature is not None else entry.temperature
    if temperature is not None:
        params["temperature"] = temperature
    top_p = request.top_p if request.top_p is not None else entry.top_p
    if top_p is not None:
        params["top_p"] = top_p
    if entry.extra_body:
        params["extra_body"] = dict(entry.extra_body)
    if request.reasoning_effort is not None:
        params["extra_body"] = dict(entry.extra_body) | {
            "reasoning_effort": request.reasoning_effort
        }
    if request.tool_definitions:
        params["tools"] = list(request.tool_definitions)
        params["tool_choice"] = "auto"
    if request.stream:
        params["stream_options"] = {"include_usage": True}
    return params


def _prompt_message_payload(message: PromptMessage) -> dict[str, object]:
    """Serialize only provider-native message fields from PromptMessage."""

    payload: dict[str, object] = {
        "role": message.role,
        "content": message.content,
    }
    if message.role == "assistant":
        tool_calls = message.metadata.get("tool_calls")
        if isinstance(tool_calls, (list, tuple)) and tool_calls:
            payload["content"] = None
            payload["tool_calls"] = list(tool_calls)
    elif message.role == "tool":
        tool_call_id = message.metadata.get("tool_call_id")
        if isinstance(tool_call_id, str) and tool_call_id:
            payload["tool_call_id"] = tool_call_id
    return payload


def normalize_completion(
    raw_response: object,
    entry: ModelEntry,
    *,
    latency_ms: int = 0,
    ttft_ms: int | None = None,
    provider_attempt: int = 1,
) -> ModelResponse:
    """Convert an OpenAI-shaped response without leaking SDK objects upward."""

    provider = entry.model_vendor
    model = _string_or_default(_field(raw_response, "model"), entry.model)
    request_id = _optional_string(_field(raw_response, "id"))
    usage = normalize_usage(_field(raw_response, "usage"))
    choices = _field(raw_response, "choices", ())
    if not isinstance(choices, (list, tuple)) or not choices:
        return ModelResponse.invalid(
            error_code="invalid_provider_response",
            provider=provider,
            access_route=entry.access_route,
            model_vendor=entry.model_vendor,
            model=model,
            usage_summary=usage,
            finish_reason="empty_response",
            request_id=request_id,
            latency_ms=latency_ms,
            ttft_ms=ttft_ms,
            provider_attempt=provider_attempt,
        )

    choice = choices[0]
    message = _field(choice, "message", {})
    finish_reason = _optional_string(_field(choice, "finish_reason"))
    common = {
        "provider": provider,
        "access_route": entry.access_route,
        "model_vendor": entry.model_vendor,
        "model": model,
        "usage_summary": usage,
        "finish_reason": finish_reason,
        "request_id": request_id,
        "latency_ms": latency_ms,
        "ttft_ms": ttft_ms,
        "provider_attempt": provider_attempt,
    }

    if finish_reason == "length":
        return ModelResponse.invalid(error_code="output_truncated", **common)

    refusal = _optional_string(_field(message, "refusal"))
    if refusal or finish_reason in {"content_filter", "sensitive"}:
        return ModelResponse.invalid(error_code="provider_refusal", **common)

    raw_tool_calls = _field(message, "tool_calls", ())
    if raw_tool_calls:
        tool_calls: list[ToolCall] = []
        if not isinstance(raw_tool_calls, (list, tuple)):
            return ModelResponse.invalid(error_code="invalid_provider_response", **common)
        for index, raw_call in enumerate(raw_tool_calls):
            function = _field(raw_call, "function", {})
            name = _optional_string(_field(function, "name"))
            if not name:
                return ModelResponse.invalid(error_code="invalid_provider_response", **common)
            arguments = _parse_tool_arguments(_field(function, "arguments", "{}"))
            if arguments is None:
                return ModelResponse.invalid(error_code="invalid_model_output", **common)
            call_id = _string_or_default(_field(raw_call, "id"), f"tool-call-{index + 1}")
            tool_calls.append(ToolCall(call_id=call_id, name=name, arguments=arguments))
        return ModelResponse(
            kind=ModelResponseKind.TOOL_CALL, tool_calls=tuple(tool_calls), **common
        )

    content = _field(message, "content")
    if isinstance(content, Mapping):
        parsed = dict(content)
    elif isinstance(content, str):
        try:
            decoded = json.loads(content)
        except (json.JSONDecodeError, TypeError):
            return ModelResponse.invalid(error_code="invalid_model_output", **common)
        if not isinstance(decoded, dict):
            return ModelResponse.invalid(error_code="invalid_model_output", **common)
        parsed = decoded
    else:
        return ModelResponse.invalid(error_code="invalid_provider_response", **common)
    if parsed == {"outcome": "silent"}:
        return ModelResponse.no_proposal(**common)
    return ModelResponse.terminal(parsed, **common)


def normalize_usage(raw_usage: object) -> UsageSummary:
    """Normalize DeepSeek, DashScope/Qwen, MiniMax and GLM usage variants."""

    if raw_usage is None:
        return UsageSummary()
    prompt_total = _first_int(raw_usage, "prompt_tokens", "input_tokens")
    output_tokens = _first_int(raw_usage, "completion_tokens", "output_tokens") or 0
    details = _field(raw_usage, "prompt_tokens_details", {})
    cached = _first_int(
        details,
        "cached_tokens",
        "cache_read_tokens",
        "prompt_cache_hit_tokens",
    )
    if cached is None:
        cached = _first_int(
            raw_usage, "prompt_cache_hit_tokens", "cache_read_tokens", "cached_tokens"
        )
    cache_written = _first_int(
        details,
        "cache_creation_input_tokens",
        "cache_write_tokens",
        "cache_creation_tokens",
    )
    if cache_written is None:
        cache_written = _first_int(
            raw_usage,
            "cache_creation_input_tokens",
            "cache_write_tokens",
            "cache_creation_tokens",
        )
    cache_missed = _first_int(raw_usage, "prompt_cache_miss_tokens", "cache_miss_tokens")

    cached = max(0, cached or 0)
    cache_written = max(0, cache_written or 0)
    if cache_missed is not None:
        uncached = max(0, cache_missed)
    elif prompt_total is not None:
        uncached = max(0, prompt_total - cached - cache_written)
    else:
        uncached = 0
    return UsageSummary(
        input_tokens=uncached,
        cache_read_tokens=cached,
        cache_write_tokens=cache_written,
        output_tokens=max(0, output_tokens),
        total_tokens=uncached + cached + cache_written + max(0, output_tokens),
    )


async def _collect_stream(
    stream: object,
    started_at: float,
    *,
    provider_attempt: int,
) -> tuple[dict[str, object], int | None]:
    if not hasattr(stream, "__aiter__"):
        raise ModelGatewayError(
            code="invalid_provider_response",
            retryable=False,
            provider_attempt=provider_attempt,
        )
    text_parts: list[str] = []
    tool_states: dict[int, dict[str, str]] = {}
    usage: object = None
    model: object = None
    response_id: object = None
    finish_reason: object = None
    ttft_ms: int | None = None
    refusal_parts: list[str] = []
    async for chunk in stream:  # type: ignore[union-attr]
        model = model or _field(chunk, "model")
        response_id = response_id or _field(chunk, "id")
        usage = _field(chunk, "usage") or usage
        choices = _field(chunk, "choices", ())
        if not choices:
            continue
        choice = choices[0]
        finish_reason = _field(choice, "finish_reason") or finish_reason
        delta = _field(choice, "delta", {})
        content = _field(delta, "content")
        reasoning = _field(delta, "reasoning_content")
        refusal = _field(delta, "refusal")
        raw_tool_calls = _field(delta, "tool_calls", ())
        if ttft_ms is None and (content or reasoning or raw_tool_calls):
            ttft_ms = _duration_ms(started_at)
        if isinstance(content, str):
            text_parts.append(content)
        if isinstance(refusal, str):
            refusal_parts.append(refusal)
        if isinstance(raw_tool_calls, (list, tuple)):
            for raw_call in raw_tool_calls:
                index = _first_int(raw_call, "index") or 0
                state = tool_states.setdefault(index, {"id": "", "name": "", "arguments": ""})
                state["id"] += _string_or_default(_field(raw_call, "id"), "")
                function = _field(raw_call, "function", {})
                state["name"] += _string_or_default(_field(function, "name"), "")
                state["arguments"] += _string_or_default(_field(function, "arguments"), "")

    message: dict[str, object] = {"content": "".join(text_parts)}
    if refusal_parts:
        message["refusal"] = "".join(refusal_parts)
    if tool_states:
        message["content"] = None
        message["tool_calls"] = [
            {
                "id": state["id"] or f"tool-call-{index + 1}",
                "function": {"name": state["name"], "arguments": state["arguments"]},
            }
            for index, state in sorted(tool_states.items())
        ]
    return {
        "id": response_id,
        "model": model,
        "choices": [{"message": message, "finish_reason": finish_reason}],
        "usage": usage,
    }, ttft_ms


def _retry_delay(error: ModelGatewayError, entry: ModelEntry, provider_attempt: int) -> float:
    retry_after = getattr(error, "retry_after_seconds", None)
    if isinstance(retry_after, (int, float)) and retry_after >= 0:
        return float(retry_after)
    return entry.retry_backoff_seconds * (2 ** max(0, provider_attempt - 1))


def _field(value: object, name: str, default: object = None) -> object:
    if isinstance(value, Mapping):
        return value.get(name, default)
    return getattr(value, name, default)


def _first_int(value: object, *names: str) -> int | None:
    for name in names:
        candidate = _field(value, name)
        if isinstance(candidate, bool):
            continue
        if isinstance(candidate, int):
            return candidate
        if isinstance(candidate, float) and candidate.is_integer():
            return int(candidate)
    return None


def _parse_tool_arguments(value: object) -> dict[str, object] | None:
    if isinstance(value, Mapping):
        return dict(value)
    if not isinstance(value, str):
        return None
    try:
        parsed = json.loads(value or "{}")
    except json.JSONDecodeError:
        return None
    return dict(parsed) if isinstance(parsed, dict) else None


def _optional_string(value: object) -> str | None:
    return value.strip() if isinstance(value, str) and value.strip() else None


def _string_or_default(value: object, default: str) -> str:
    return _optional_string(value) or default


def _duration_ms(started_at: float) -> int:
    return max(0, round((perf_counter() - started_at) * 1000))
