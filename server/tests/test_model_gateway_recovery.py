from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest
from support_agent_context import build_test_snapshot

from echo_server.agents.contracts import (
    AgentInvocation,
    AgentRunStatus,
    ContextInputRef,
    ConversationScope,
    Correlation,
    ExecutionPolicy,
    FailureCategory,
    InvocationIdentity,
    OutputContractRef,
)
from echo_server.agents.harness import EchoNativeBackend
from echo_server.agents.harness.recovery import classify_gateway_error
from echo_server.services.model_gateway import (
    FakeModelGateway,
    ModelConfigurationError,
    ModelEntry,
    ModelGatewayError,
    ModelRegistry,
    ModelRequest,
    ModelResponse,
    ModelResponseKind,
    OpenAICompatibleGateway,
    PromptMessage,
    classify_configuration_error,
    classify_provider_error,
    normalize_completion,
)


class FakeProviderError(Exception):
    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        super().__init__("provider detail must not escape")
        self.status_code = status_code
        self.response = SimpleNamespace(
            headers={"Retry-After": retry_after} if retry_after is not None else {}
        )


class FakeCompletions:
    def __init__(self, responses: list[object]) -> None:
        self.responses = list(responses)
        self.calls: list[dict[str, object]] = []

    async def create(self, **kwargs: object) -> object:
        self.calls.append(kwargs)
        response = self.responses.pop(0)
        if isinstance(response, Exception):
            raise response
        return response


class FakeClient:
    def __init__(self, completions: FakeCompletions) -> None:
        self.chat = SimpleNamespace(completions=completions)


class FixedClock:
    def __init__(self, value: datetime) -> None:
        self.value = value

    def __call__(self) -> datetime:
        return self.value


def make_entry(
    *,
    max_retries: int = 1,
    retry_backoff_seconds: float = 0.5,
    enabled: bool = True,
) -> ModelEntry:
    return ModelEntry(
        entry_id="deepseek_v4_flash",
        model_vendor="deepseek",
        model="deepseek-v4-flash",
        base_url="https://example.test/v1",
        credential_ref="test",
        access_route="deepseek-direct-evaluation",
        enabled=enabled,
        max_retries=max_retries,
        retry_backoff_seconds=retry_backoff_seconds,
    )


def make_registry(
    entry: ModelEntry,
    *,
    credentials: dict[str, str] | None = None,
) -> ModelRegistry:
    return ModelRegistry(
        backend="openai_compatible",
        active_profile="light",
        profiles={"light": entry.entry_id},
        entries={entry.entry_id: entry},
        credentials={"test": "test-key"} if credentials is None else credentials,
    )


def make_request(**updates: object) -> ModelRequest:
    values: dict[str, object] = {
        "invocation_id": uuid4(),
        "trace_id": uuid4(),
        "agent_id": "test-agent",
        "model_profile": "light",
        "attempt": 1,
        "step_index": 1,
        "messages": (PromptMessage(role="user", content="hello"),),
        "output_schema": "character_message",
    }
    values.update(updates)
    return ModelRequest(**values)


def make_invocation() -> AgentInvocation:
    context = build_test_snapshot(stage_summary="测试")
    return AgentInvocation(
        identity=InvocationIdentity(agent_id="xiaojin.character"),
        scope=ConversationScope(
            conversation_id=context.conversation_id,
            character_id=context.character_id,
        ),
        context=context,
        context_input=ContextInputRef(
            snapshot_id=context.context_version,
            snapshot_schema_version=context.snapshot_version,
            snapshot_fingerprint=context.input_fingerprint,
        ),
        output_contract=OutputContractRef(kind="character_message", version="v2"),
        execution_policy=ExecutionPolicy(),
        correlation=Correlation(task_id=uuid4(), trace_id=uuid4()),
    )


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (401, "authentication", False),
        (402, "quota_exceeded", False),
        (429, "rate_limited", True),
        (503, "temporary_unavailable", True),
        (400, "invalid_request", False),
    ],
)
def test_provider_errors_are_stable_and_redacted(
    status_code: int,
    expected_code: str,
    retryable: bool,
) -> None:
    error = classify_provider_error(
        FakeProviderError(status_code, retry_after="2"),
        provider_attempt=4,
    )

    assert error.code == expected_code
    assert error.retryable is retryable
    assert error.provider_attempt == 4
    assert error.retry_after_seconds == (2.0 if retryable else None)
    assert "provider detail" not in str(error)


def test_configuration_errors_are_non_retryable_gateway_errors() -> None:
    error = classify_configuration_error(ModelConfigurationError("bad model profile"))

    assert error.code == "model_configuration_invalid"
    assert error.retryable is False
    assert error.provider_attempt == 0
    assert "bad model profile" not in str(error)


def test_gateway_recovery_maps_configuration_error_to_configuration_category() -> None:
    failure = classify_gateway_error(
        ModelGatewayError(code="model_configuration_invalid", retryable=False)
    )

    assert failure.category is FailureCategory.CONFIGURATION
    assert failure.retryable is False


@pytest.mark.asyncio
async def test_gateway_wraps_disabled_entry_without_calling_provider() -> None:
    entry = make_entry(enabled=False)
    completions = FakeCompletions([])
    gateway = OpenAICompatibleGateway(
        make_registry(entry),
        client_factory=lambda _entry, _key: FakeClient(completions),
    )

    with pytest.raises(ModelGatewayError) as raised:
        await gateway.generate(make_request())

    assert raised.value.code == "model_configuration_invalid"
    assert raised.value.provider_attempt == 0
    assert completions.calls == []


@pytest.mark.asyncio
async def test_gateway_reports_missing_credential_without_provider_attempt() -> None:
    entry = make_entry()
    completions = FakeCompletions([])
    gateway = OpenAICompatibleGateway(
        make_registry(entry, credentials={}),
        client_factory=lambda _entry, _key: FakeClient(completions),
    )

    with pytest.raises(ModelGatewayError) as raised:
        await gateway.generate(make_request())

    assert raised.value.code == "provider_not_configured"
    assert raised.value.provider_attempt == 0
    assert completions.calls == []


@pytest.mark.asyncio
async def test_gateway_retries_rate_limit_using_retry_after() -> None:
    completions = FakeCompletions(
        [
            FakeProviderError(429, retry_after="2"),
            {"choices": [{"message": {"content": '{"utterance":"ok"}'}}]},
        ]
    )
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    gateway = OpenAICompatibleGateway(
        make_registry(make_entry()),
        client_factory=lambda _entry, _key: FakeClient(completions),
        sleep=sleep,
    )

    response = await gateway.generate(make_request())

    assert response.kind is ModelResponseKind.TERMINAL
    assert response.provider_attempt == 2
    assert delays == [2.0]
    assert len(completions.calls) == 2


@pytest.mark.asyncio
async def test_gateway_uses_exponential_backoff_and_raises_after_attempt_limit() -> None:
    completions = FakeCompletions([FakeProviderError(503), FakeProviderError(503)])
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    gateway = OpenAICompatibleGateway(
        make_registry(make_entry(max_retries=1, retry_backoff_seconds=0.25)),
        client_factory=lambda _entry, _key: FakeClient(completions),
        sleep=sleep,
    )

    with pytest.raises(ModelGatewayError) as raised:
        await gateway.generate(make_request())

    assert raised.value.code == "temporary_unavailable"
    assert raised.value.provider_attempt == 2
    assert delays == [0.25]
    assert len(completions.calls) == 2


@pytest.mark.asyncio
async def test_gateway_does_not_retry_non_retryable_provider_error() -> None:
    completions = FakeCompletions([FakeProviderError(401)])
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    gateway = OpenAICompatibleGateway(
        make_registry(make_entry()),
        client_factory=lambda _entry, _key: FakeClient(completions),
        sleep=sleep,
    )

    with pytest.raises(ModelGatewayError) as raised:
        await gateway.generate(make_request())

    assert raised.value.code == "authentication"
    assert delays == []
    assert len(completions.calls) == 1


@pytest.mark.asyncio
async def test_gateway_preserves_rate_limit_when_deadline_cannot_fit_retry_delay() -> None:
    now = datetime(2026, 9, 27, 12, 0, tzinfo=UTC)
    completions = FakeCompletions([FakeProviderError(429, retry_after="2")])
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    gateway = OpenAICompatibleGateway(
        make_registry(make_entry()),
        client_factory=lambda _entry, _key: FakeClient(completions),
        sleep=sleep,
        clock=FixedClock(now),
    )

    with pytest.raises(ModelGatewayError) as raised:
        await gateway.generate(make_request(deadline_utc=now + timedelta(seconds=1)))

    assert raised.value.code == "rate_limited"
    assert raised.value.retry_after_seconds == 2.0
    assert delays == []
    assert len(completions.calls) == 1


@pytest.mark.asyncio
async def test_gateway_records_provider_attempt_on_second_attempt_timeout() -> None:
    completions = FakeCompletions([FakeProviderError(503), TimeoutError()])
    delays: list[float] = []

    async def sleep(delay: float) -> None:
        delays.append(delay)

    gateway = OpenAICompatibleGateway(
        make_registry(make_entry()),
        client_factory=lambda _entry, _key: FakeClient(completions),
        sleep=sleep,
    )

    with pytest.raises(ModelGatewayError) as raised:
        await gateway.generate(make_request())

    assert raised.value.code == "timeout"
    assert raised.value.provider_attempt == 2
    assert delays == [0.5]


@pytest.mark.parametrize(
    ("raw_response", "expected_code"),
    [
        ({"choices": []}, "invalid_provider_response"),
        (
            {"choices": [{"message": {"content": "not json"}}]},
            "invalid_model_output",
        ),
        (
            {
                "choices": [
                    {
                        "finish_reason": "length",
                        "message": {"content": '{"utterance":"cut"}'},
                    }
                ]
            },
            "output_truncated",
        ),
        (
            {"choices": [{"message": {"content": None, "refusal": "拒绝"}}]},
            "provider_refusal",
        ),
        (
            {
                "choices": [
                    {
                        "message": {
                            "tool_calls": [
                                {
                                    "function": {
                                        "name": "memory_search",
                                        "arguments": "not json",
                                    }
                                }
                            ]
                        }
                    }
                ]
            },
            "invalid_model_output",
        ),
    ],
)
def test_normalize_completion_preserves_response_error_code(
    raw_response: dict[str, object],
    expected_code: str,
) -> None:
    response = normalize_completion(raw_response, make_entry())

    assert response.kind is ModelResponseKind.INVALID
    assert response.error_code == expected_code


@pytest.mark.asyncio
async def test_gateway_returns_response_error_without_provider_retry() -> None:
    completions = FakeCompletions(
        [
            {"choices": [{"message": {"content": "not json"}}]},
            {"choices": [{"message": {"content": '{"utterance":"ok"}'}}]},
        ]
    )
    gateway = OpenAICompatibleGateway(
        make_registry(make_entry()),
        client_factory=lambda _entry, _key: FakeClient(completions),
    )

    response = await gateway.generate(make_request())

    assert response.kind is ModelResponseKind.INVALID
    assert response.error_code == "invalid_model_output"
    assert len(completions.calls) == 1


@pytest.mark.asyncio
async def test_harness_keeps_provider_refusal_terminal() -> None:
    harness = EchoNativeBackend(
        FakeModelGateway([ModelResponse.invalid(error_code="provider_refusal")]),
        agent_id="xiaojin.character",
    )

    result = await harness.run(make_invocation())

    assert result.status is AgentRunStatus.FAILED
    assert result.diagnostic_codes == ("provider_refusal",)


@pytest.mark.asyncio
async def test_harness_repairs_truncated_output_in_the_same_run() -> None:
    harness = EchoNativeBackend(
        FakeModelGateway(
            [
                ModelResponse.invalid(error_code="output_truncated"),
                ModelResponse.terminal(
                    {
                        "thought": "我重新整理了输出。",
                        "utterance": "我在听。",
                    }
                ),
            ]
        ),
        agent_id="xiaojin.character",
    )

    invocation = make_invocation().model_copy(
        update={
            "execution_policy": ExecutionPolicy(
                max_model_steps=2,
                max_model_requests=2,
            )
        }
    )
    result = await harness.run(invocation)

    assert result.status is AgentRunStatus.COMPLETED
    assert result.repair_count == 1
