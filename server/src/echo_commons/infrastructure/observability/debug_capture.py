from __future__ import annotations

import base64
import json
import os
from collections.abc import Awaitable, Callable, Mapping
from dataclasses import asdict, is_dataclass
from datetime import UTC, date, datetime, time
from pathlib import Path
from threading import Lock
from typing import TYPE_CHECKING
from uuid import UUID, uuid4

from echo_commons.app.settings import DEFAULT_DEBUG_CAPTURE_PATH, Settings

if TYPE_CHECKING:
    from echo_commons.agents.contracts import AgentInvocation, AgentRunResult
    from echo_commons.infrastructure.models.protocol import ModelRequest, ModelResponse
    from echo_commons.infrastructure.models.registry import ModelEntry


DEBUG_CAPTURE_SCHEMA_VERSION = 1


class AgentDebugCapture:
    """Write complete local Agent diagnostics without touching normal logs."""

    def __init__(self, root: str | Path) -> None:
        self.root = Path(root).expanduser().resolve()
        created_at = datetime.now(UTC)
        self.created_at_utc = _timestamp(created_at)
        self.session_id = (
            f"{created_at.strftime('%Y%m%dT%H%M%S%z')}-{os.getpid()}-{uuid4().hex[:8]}"
        )
        self.session_dir = self.root / self.session_id
        self._lock = Lock()
        self._sequence = 0
        self._session_initialized = False

    @classmethod
    def from_settings(cls, settings: Settings) -> AgentDebugCapture | None:
        """Create capture only for an explicit non-production local run."""

        if not settings.debug_capture_enabled:
            return None
        if settings.environment.strip().lower() in {"prod", "production"}:
            return None
        return cls(settings.debug_capture_path or DEFAULT_DEBUG_CAPTURE_PATH)

    @property
    def directory(self) -> Path:
        """Return the session directory where the next capture files are written."""

        return self.session_dir

    def capture_agent_started(self, invocation: AgentInvocation, *, backend: str) -> Path:
        return self._write(
            "agent_run.started",
            {
                "agent": {
                    "backend": backend,
                    "agentId": invocation.identity.agent_id,
                    "agentKind": invocation.identity.agent_kind,
                    "harnessVersion": invocation.execution_policy.harness_version,
                },
                "correlation": _invocation_correlation(invocation),
                "input": {"invocation": _jsonable(invocation)},
            },
        )

    def capture_agent_completed(
        self,
        invocation: AgentInvocation,
        result: AgentRunResult,
        *,
        backend: str,
    ) -> Path:
        return self._write(
            "agent_run.completed",
            {
                "agent": {
                    "backend": backend,
                    "agentId": invocation.identity.agent_id,
                    "agentKind": invocation.identity.agent_kind,
                    "harnessVersion": invocation.execution_policy.harness_version,
                },
                "correlation": _invocation_correlation(invocation),
                "input": {"invocationId": str(invocation.identity.invocation_id)},
                "output": {"agentRunResult": _agent_run_result_json(result)},
            },
        )

    def capture_agent_failed(
        self,
        invocation: AgentInvocation,
        error: BaseException,
        *,
        backend: str,
    ) -> Path:
        return self._write(
            "agent_run.failed",
            {
                "agent": {
                    "backend": backend,
                    "agentId": invocation.identity.agent_id,
                    "agentKind": invocation.identity.agent_kind,
                    "harnessVersion": invocation.execution_policy.harness_version,
                },
                "correlation": _invocation_correlation(invocation),
                "input": {"invocationId": str(invocation.identity.invocation_id)},
                "error": _error_details(error),
            },
        )

    def capture_model_call(
        self,
        request: ModelRequest,
        entry: ModelEntry,
        *,
        provider_request: Mapping[str, object],
        raw_response: object | None,
        normalized_response: ModelResponse | None,
        provider_attempt: int,
        ttft_ms: int | None = None,
        error: BaseException | None = None,
    ) -> Path:
        """Capture one actual Provider attempt, including invalid responses."""

        payload: dict[str, object] = {
            "correlation": {
                "traceId": str(request.trace_id),
                "invocationId": str(request.invocation_id),
                "agentId": request.agent_id,
                "attempt": request.attempt,
                "stepIndex": request.step_index,
            },
            "route": {
                "modelProfile": request.model_profile,
                "modelEntryId": request.model_entry_id,
                "provider": entry.model_vendor,
                "accessRoute": entry.access_route,
                "modelVendor": entry.model_vendor,
                "model": entry.model,
                "providerAttempt": provider_attempt,
            },
            "input": {
                "modelRequest": _jsonable(request),
                "providerRequest": _jsonable(provider_request),
            },
            "output": {
                "rawProviderResponse": _jsonable(raw_response),
                "normalizedModelResponse": _jsonable(normalized_response),
            },
        }
        if ttft_ms is not None:
            payload["timing"] = {"ttftMs": ttft_ms}
        if error is not None:
            payload["error"] = _error_details(error)
        return self._write("model_call", payload)

    def _write(self, event_type: str, payload: Mapping[str, object]) -> Path:
        with self._lock:
            self._ensure_session()
            self._sequence += 1
            capture_id = f"{self.session_id}-{self._sequence:06d}"
            document = {
                "schemaVersion": DEBUG_CAPTURE_SCHEMA_VERSION,
                "captureId": capture_id,
                "sessionId": self.session_id,
                "sequence": self._sequence,
                "eventType": event_type,
                "capturedAtUtc": _timestamp(datetime.now(UTC)),
                **_jsonable(dict(payload)),
            }
            path = self.session_dir / f"{self._sequence:06d}-{_safe_name(event_type)}.json"
            temporary = path.with_suffix(".json.tmp")
            temporary.write_text(
                json.dumps(document, ensure_ascii=False, indent=2, default=str) + "\n",
                encoding="utf-8",
            )
            temporary.replace(path)
            return path

    def _ensure_session(self) -> None:
        if self._session_initialized:
            return
        self.session_dir.mkdir(parents=True, exist_ok=True)
        session = {
            "schemaVersion": DEBUG_CAPTURE_SCHEMA_VERSION,
            "sessionId": self.session_id,
            "createdAtUtc": self.created_at_utc,
            "processId": os.getpid(),
            "purpose": "local Agent model input/output debugging",
        }
        (self.session_dir / "session.json").write_text(
            json.dumps(session, ensure_ascii=False, indent=2) + "\n",
            encoding="utf-8",
        )
        self._session_initialized = True


async def run_with_debug_capture(
    capture: AgentDebugCapture | None,
    invocation: AgentInvocation,
    *,
    backend: str,
    operation: Callable[[], Awaitable[AgentRunResult]],
) -> AgentRunResult:
    """Run one backend operation while keeping diagnostics strictly best effort."""

    if capture is not None:
        _safe_capture(capture.capture_agent_started, invocation, backend=backend)
    try:
        result = await operation()
    except BaseException as exc:
        if capture is not None:
            _safe_capture(capture.capture_agent_failed, invocation, exc, backend=backend)
        raise
    if capture is not None:
        _safe_capture(capture.capture_agent_completed, invocation, result, backend=backend)
    return result


def _safe_capture(method: Callable[..., object], *args: object, **kwargs: object) -> None:
    try:
        method(*args, **kwargs)
    except Exception:
        # A full-content diagnostic channel must never change Agent semantics.
        return


def _invocation_correlation(invocation: AgentInvocation) -> dict[str, object]:
    payload = {
        "traceId": str(invocation.correlation.trace_id),
        "invocationId": str(invocation.identity.invocation_id),
        "attempt": invocation.identity.attempt,
    }
    if invocation.correlation.task_id is not None:
        payload["taskId"] = str(invocation.correlation.task_id)
    return payload


def _agent_run_result_json(result: AgentRunResult) -> object:
    """Serialize the typed Agent Run result."""

    return _jsonable(result)


def _error_details(error: BaseException) -> dict[str, object]:
    details: dict[str, object] = {
        "type": error.__class__.__name__,
    }
    code = getattr(error, "code", None)
    if isinstance(code, str) and code:
        details["code"] = code
    status_code = getattr(error, "status_code", None)
    if isinstance(status_code, int):
        details["statusCode"] = status_code
    retryable = getattr(error, "retryable", None)
    if isinstance(retryable, bool):
        details["retryable"] = retryable
    return details


def _safe_name(value: str) -> str:
    return "".join(
        character if character.isalnum() or character in "._-" else "_" for character in value
    )


def _timestamp(value: datetime) -> str:
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def _jsonable(value: object, *, seen: set[int] | None = None) -> object:
    """Convert SDK/Pydantic objects without truncating their content."""

    if value is None or isinstance(value, str | int | float | bool):
        return value
    if isinstance(value, UUID):
        return str(value)
    if isinstance(value, datetime | date | time):
        return value.isoformat()
    if isinstance(value, bytes):
        return {
            "encoding": "base64",
            "data": base64.b64encode(value).decode("ascii"),
        }

    active = seen if seen is not None else set()
    identity = id(value)
    if identity in active:
        return "<recursive>"
    active.add(identity)
    try:
        if isinstance(value, Mapping):
            return {str(key): _jsonable(item, seen=active) for key, item in value.items()}
        if isinstance(value, (list, tuple, set, frozenset)):
            return [_jsonable(item, seen=active) for item in value]
        model_dump = getattr(value, "model_dump", None)
        if callable(model_dump):
            try:
                return _jsonable(model_dump(mode="json"), seen=active)
            except TypeError:
                return _jsonable(model_dump(), seen=active)
        to_dict = getattr(value, "to_dict", None)
        if callable(to_dict):
            return _jsonable(to_dict(), seen=active)
        if is_dataclass(value) and not isinstance(value, type):
            return _jsonable(asdict(value), seen=active)
        attributes = getattr(value, "__dict__", None)
        if isinstance(attributes, dict):
            return {
                str(key): _jsonable(item, seen=active)
                for key, item in attributes.items()
                if not str(key).startswith("_")
            }
        return str(value)
    finally:
        active.discard(identity)


__all__ = [
    "AgentDebugCapture",
    "DEBUG_CAPTURE_SCHEMA_VERSION",
    "run_with_debug_capture",
]
