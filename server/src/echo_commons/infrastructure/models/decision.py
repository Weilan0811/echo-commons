import asyncio
import json
import logging
from datetime import UTC, datetime, timedelta
from time import perf_counter

import httpx

from echo_commons.execution.model_budget import ModelBudget
from echo_commons.infrastructure.models.decision_protocol import (
    DecisionRequest,
    DecisionResponse,
    DecisionRoute,
)
from echo_commons.infrastructure.models.metrics import ProviderUsageTracker
from echo_commons.infrastructure.models.protocol import BeforeModelRequest, ModelGatewayError
from echo_commons.infrastructure.models.registry import ModelConfigurationError, ModelRegistry
from echo_commons.infrastructure.observability.debug_capture import AgentDebugCapture
from echo_commons.infrastructure.observability.logging import get_logger, log_event

logger = get_logger("decision_gateway")


class DecisionGateway:
    def __init__(
        self,
        registry: ModelRegistry,
        budget: ModelBudget,
        *,
        debug_capture: AgentDebugCapture | None = None,
    ) -> None:
        if not registry.decision.enabled:
            raise ModelConfigurationError("Disabled decisions must not construct a gateway")
        self.registry, self.budget, self.debug_capture = registry, budget, debug_capture
        self.usage_tracker = ProviderUsageTracker()
        self._client: httpx.AsyncClient | None = None

    def prepare(self, request: DecisionRequest) -> DecisionRequest:
        profile = request.model_profile or self.registry.decision.profile
        route = request.route
        retries = request.max_provider_retries
        if route is None:
            entry = self.registry.resolve(profile, request.model_entry_id)
            if entry.protocol != "startlux_decision":
                raise ModelConfigurationError("decisions require startlux_decision protocol")
            route = DecisionRoute(
                entry_id=entry.entry_id,
                model_vendor=entry.model_vendor,
                model=entry.model,
                base_url=entry.base_url,
                credential_ref=entry.credential_ref,
                access_route=entry.access_route,
                request_timeout_seconds=entry.request_timeout_seconds,
                retry_backoff_seconds=entry.retry_backoff_seconds,
                input_max_chars=self.registry.decision.input_max_chars,
            )
            if retries is None:
                retries = entry.max_retries
        elif request.model_entry_id != route.entry_id or retries is None:
            raise ModelConfigurationError("prepared decision route is incomplete or inconsistent")
        return request.model_copy(
            update={
                "model_profile": profile,
                "model_entry_id": route.entry_id,
                "route": route,
                "controls": request.controls or self.registry.decision.controls,
                "deadline_utc": request.deadline_utc
                or datetime.now(UTC) + timedelta(seconds=self.registry.decision.timeout_seconds),
                "max_provider_retries": retries,
            },
            deep=True,
        )

    async def decide(
        self, request: DecisionRequest, *, before_request: BeforeModelRequest | None = None
    ) -> DecisionResponse:
        try:
            request = self.prepare(request)
            entry = request.route
        except ModelConfigurationError as exc:
            raise ModelGatewayError(code=exc.code, retryable=False, provider_attempt=0) from exc
        payload = request.payload()
        if len(json.dumps(payload, ensure_ascii=False)) > entry.input_max_chars:
            raise ModelGatewayError(code="input_too_large", retryable=False, provider_attempt=0)
        credential = self.registry.credential_for(entry)
        if entry.credential_ref and credential is None:
            raise ModelGatewayError(
                code="provider_not_configured", retryable=False, provider_attempt=0
            )
        remaining = (request.deadline_utc - datetime.now(UTC)).total_seconds()
        if remaining <= 0:
            raise ModelGatewayError(code="timeout", retryable=True, provider_attempt=0)
        attempt = 0
        try:
            # 等待并发额度和重试也使用同一个调用期限。
            async with asyncio.timeout(max(0, remaining)):
                async with self.budget.slot(0):
                    for attempt in range(1, request.max_provider_retries + 2):
                        if before_request is not None:
                            await before_request()
                        if self._client is None:
                            self._client = httpx.AsyncClient(trust_env=False)
                        try:
                            response = await self._call(
                                request, entry, payload, credential, attempt
                            )
                        except ModelGatewayError as error:
                            if not error.retryable or attempt > request.max_provider_retries:
                                raise
                            await asyncio.sleep(
                                error.retry_after_seconds or entry.retry_backoff_seconds
                            )
                            continue
                        self.usage_tracker.record(entry.model_vendor, response.usage_summary)
                        return response
        except TimeoutError as exc:
            log_event(
                logger,
                logging.WARNING,
                "model.call.failed",
                correlation_id=request.trace_id,
                error_code="timeout",
                provider_attempt=attempt,
            )
            raise ModelGatewayError(
                code="timeout", retryable=True, provider_attempt=attempt
            ) from exc
        raise RuntimeError("Decision request did not finish")

    async def _call(self, request, entry, payload, credential, attempt) -> DecisionResponse:
        started = perf_counter()
        headers = {"x-request-id": str(request.invocation_id)}
        if credential:
            headers["Authorization"] = f"Bearer {credential}"
        raw, normalized, failure = None, None, None
        self._capture(
            "capture_model_started",
            request,
            entry,
            provider_request=payload,
            provider_attempt=attempt,
        )
        log_event(
            logger,
            logging.INFO,
            "model.call.started",
            correlation_id=request.trace_id,
            model_profile=request.model_profile,
            provider=entry.model_vendor,
            model=entry.model,
            provider_attempt=attempt,
        )
        try:
            response = await self._client.post(
                entry.base_url + "/v1/systemone",
                json=payload,
                headers=headers,
                timeout=entry.request_timeout_seconds,
            )
            try:
                raw = response.json()
            except ValueError:
                raw = response.text
            response.raise_for_status()
            normalized = DecisionResponse.model_validate(
                {
                    **raw,
                    "model_entry_id": entry.entry_id,
                    "latency_ms": int((perf_counter() - started) * 1000),
                    "provider_attempt": attempt,
                    "request_id": response.headers.get("x-request-id"),
                }
            )
            normalized.validate_answers(request)
            if normalized.model != entry.model:
                raise ModelGatewayError(
                    code="model_identity_mismatch", retryable=False, provider_attempt=attempt
                )
            log_event(
                logger,
                logging.INFO,
                "model.call.completed",
                correlation_id=request.trace_id,
                provider=entry.model_vendor,
                model=normalized.model,
                latency_ms=normalized.latency_ms,
                provider_attempt=attempt,
                usage=normalized.usage.model_dump() if normalized.usage else None,
            )
            return normalized
        except httpx.HTTPError as exc:
            failure = _http_failure(exc, attempt)
            raise failure from exc
        except (ValueError, TypeError) as exc:
            failure = ModelGatewayError(
                code="invalid_provider_response", retryable=False, provider_attempt=attempt
            )
            raise failure from exc
        except BaseException as exc:
            failure = exc
            raise
        finally:
            self._capture(
                "capture_model_call",
                request,
                entry,
                provider_request=payload,
                raw_response=raw,
                normalized_response=normalized,
                provider_attempt=attempt,
                error=failure,
            )
            if failure is not None:
                log_event(
                    logger,
                    logging.WARNING,
                    "model.call.failed",
                    correlation_id=request.trace_id,
                    provider=entry.model_vendor,
                    model=entry.model,
                    provider_attempt=attempt,
                    latency_ms=int((perf_counter() - started) * 1000),
                    error_code=getattr(failure, "code", "cancelled"),
                )

    def _capture(self, method, *args, **kwargs) -> None:
        if self.debug_capture is not None:
            try:
                getattr(self.debug_capture, method)(*args, **kwargs)
            except Exception:
                logger.warning("Decision diagnostic capture failed", exc_info=True)

    async def close(self) -> None:
        if self._client is not None:
            await self._client.aclose()


def _http_failure(error: httpx.HTTPError, attempt: int) -> ModelGatewayError:
    status = error.response.status_code if isinstance(error, httpx.HTTPStatusError) else None
    if isinstance(error, httpx.TimeoutException):
        code, retryable = "timeout", True
    elif status == 429:
        code, retryable = "rate_limited", True
    elif status in (401, 403):
        code, retryable = "authentication", False
    elif status == 413:
        code, retryable = "input_too_large", False
    elif status is None or status in (408, 409, 425) or status >= 500:
        code, retryable = "temporary_unavailable", True
    else:
        code, retryable = "invalid_request", False
    retry_after = None
    if status == 429:
        value = error.response.headers.get("Retry-After", "")
        if value.isdigit():
            retry_after = float(value)
    return ModelGatewayError(
        code=code,
        retryable=retryable,
        status_code=status,
        provider_attempt=attempt,
        retry_after_seconds=retry_after,
        exception_type=type(error).__name__,
    )
