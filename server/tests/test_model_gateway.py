from __future__ import annotations

from datetime import UTC, datetime, timedelta
from types import SimpleNamespace
from uuid import uuid4

import pytest

from echo_server.agents.contracts import UsageSummary
from echo_server.services.model_gateway import (
    ModelEntry,
    ModelGatewayError,
    ModelRegistry,
    ModelRequest,
    ModelResponseKind,
    OpenAICompatibleGateway,
    PromptMessage,
    classify_provider_error,
    load_model_registry,
    normalize_completion,
    normalize_usage,
)


class FakeProviderError(Exception):
    def __init__(self, status_code: int, retry_after: str | None = None) -> None:
        super().__init__("provider text must not escape")
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


def make_entry(
    entry_id: str = "deepseek_v4_flash",
    *,
    vendor: str = "deepseek",
    route: str = "deepseek-direct-evaluation",
    model: str = "deepseek-v4-flash",
    max_retries: int = 1,
) -> ModelEntry:
    return ModelEntry(
        entry_id=entry_id,
        model_vendor=vendor,
        model=model,
        base_url="https://example.test/v1",
        credential_ref="test",
        access_route=route,
        max_retries=max_retries,
        retry_backoff_seconds=0,
    )


def make_registry(entry: ModelEntry) -> ModelRegistry:
    return ModelRegistry(
        backend="openai_compatible",
        active_profile="light",
        profiles={"light": entry.entry_id},
        entries={entry.entry_id: entry},
        credentials={"test": "test-key"},
    )


def make_request(**updates: object) -> ModelRequest:
    values: dict[str, object] = {
        "invocation_id": uuid4(),
        "trace_id": uuid4(),
        "agent_id": "test-agent",
        "model_profile": "light",
        "attempt": 1,
        "step_index": 1,
        "messages": (
            PromptMessage(role="system", content="stable prefix"),
            PromptMessage(role="user", content="hello"),
        ),
        "output_schema": "character_message",
    }
    values.update(updates)
    return ModelRequest(**values)


def test_registry_contains_four_provisional_entries(tmp_path) -> None:
    registry = load_model_registry(secrets_path=tmp_path / "missing-model-secrets.toml")

    assert set(registry.entries) == {
        "deepseek_v4_flash",
        "minimax_m3",
        "qwen38_flash",
        "glm53_flash",
    }
    assert registry.profiles == {"light": "deepseek_v4_flash", "strong": "glm53_flash"}
    assert registry.entries["deepseek_v4_flash"].access_route == "deepseek-direct-evaluation"
    assert registry.entries["minimax_m3"].access_route == "dashscope-evaluation"
    assert registry.entries["qwen38_flash"].access_route == "dashscope-evaluation"
    assert registry.entries["glm53_flash"].access_route == "dashscope-evaluation"
    assert registry.should_use_real_agent() is False


def test_normalize_usage_supports_deepseek_fields() -> None:
    usage = normalize_usage(
        {
            "prompt_tokens": 100,
            "prompt_cache_hit_tokens": 70,
            "prompt_cache_miss_tokens": 30,
            "completion_tokens": 12,
            "total_tokens": 112,
        }
    )

    assert usage == UsageSummary(
        input_tokens=30,
        cache_read_tokens=70,
        output_tokens=12,
        total_tokens=112,
    )
    assert usage.cache_hit_ratio == pytest.approx(0.7)


def test_normalize_usage_supports_dashscope_cache_fields() -> None:
    usage = normalize_usage(
        {
            "prompt_tokens": 100,
            "prompt_tokens_details": {
                "cached_tokens": 60,
                "cache_creation_input_tokens": 10,
            },
            "completion_tokens": 8,
        }
    )

    assert usage.input_tokens == 30
    assert usage.cache_read_tokens == 60
    assert usage.cache_write_tokens == 10
    assert usage.output_tokens == 8
    assert usage.total_tokens == 108


def test_normalize_completion_parses_structured_json() -> None:
    response = normalize_completion(
        {
            "id": "completion-1",
            "model": "deepseek-v4-flash",
            "choices": [
                {
                    "finish_reason": "stop",
                    "message": {
                        "role": "assistant",
                        "content": '{"utterance":"ok"}',
                    },
                }
            ],
        },
        make_entry(),
    )

    assert response.kind is ModelResponseKind.TERMINAL
    assert response.output == {"utterance": "ok"}
    assert response.request_id == "completion-1"


@pytest.mark.asyncio
async def test_gateway_preserves_messages_and_records_provider_group_usage() -> None:
    completions = FakeCompletions(
        [
            {
                "id": "completion-1",
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {
                            "role": "assistant",
                            "content": '{"utterance":"ok"}',
                        },
                    }
                ],
                "usage": {
                    "prompt_tokens": 100,
                    "prompt_cache_hit_tokens": 50,
                    "prompt_cache_miss_tokens": 50,
                    "completion_tokens": 10,
                },
            }
        ]
    )
    entry = make_entry()
    client = FakeClient(completions)
    gateway = OpenAICompatibleGateway(
        make_registry(entry), client_factory=lambda _entry, _key: client
    )
    request = make_request()

    response = await gateway.generate(request)

    assert response.provider == "deepseek"
    assert response.access_route == "deepseek-direct-evaluation"
    assert response.model_vendor == "deepseek"
    assert response.provider_attempt == 1
    assert completions.calls[0]["messages"] == [
        {"role": "system", "content": "stable prefix"},
        {"role": "user", "content": "hello"},
    ]
    assert completions.calls[0]["response_format"] == {"type": "json_object"}
    aggregate = gateway.usage_tracker.snapshot()["deepseek"]
    assert aggregate.model_request_count == 1
    assert aggregate.cache_hit_ratio == pytest.approx(0.5)


@pytest.mark.asyncio
async def test_gateway_serializes_native_tool_call_message_sequence() -> None:
    completions = FakeCompletions(
        [{"choices": [{"message": {"content": '{"kind":"character_message","utterance":"ok"}'}}]}]
    )
    entry = make_entry(max_retries=0)
    gateway = OpenAICompatibleGateway(
        make_registry(entry), client_factory=lambda _entry, _key: FakeClient(completions)
    )

    await gateway.generate(
        make_request(
            messages=(
                PromptMessage(role="system", content="stable prefix"),
                PromptMessage(role="user", content="查一下"),
                PromptMessage(
                    role="assistant",
                    content="",
                    metadata={
                        "tool_calls": [
                            {
                                "id": "memory-1",
                                "type": "function",
                                "function": {
                                    "name": "memory_search",
                                    "arguments": '{"topic":"雨"}',
                                },
                            }
                        ]
                    },
                ),
                PromptMessage(
                    role="tool",
                    content='{"found":true}',
                    metadata={
                        "tool_call_id": "memory-1",
                        "tool_name": "must-not-leak",
                    },
                ),
            )
        )
    )

    assert completions.calls[0]["messages"] == [
        {"role": "system", "content": "stable prefix"},
        {"role": "user", "content": "查一下"},
        {
            "role": "assistant",
            "content": None,
            "tool_calls": [
                {
                    "id": "memory-1",
                    "type": "function",
                    "function": {
                        "name": "memory_search",
                        "arguments": '{"topic":"雨"}',
                    },
                }
            ],
        },
        {
            "role": "tool",
            "content": '{"found":true}',
            "tool_call_id": "memory-1",
        },
    ]


@pytest.mark.asyncio
async def test_gateway_retries_rate_limit_without_leaking_provider_message() -> None:
    completions = FakeCompletions(
        [
            FakeProviderError(429, "0"),
            {
                "model": "deepseek-v4-flash",
                "choices": [
                    {
                        "finish_reason": "stop",
                        "message": {"content": '{"kind":"character_message","utterance":"ok"}'},
                    }
                ],
            },
        ]
    )
    entry = make_entry(max_retries=1)
    gateway = OpenAICompatibleGateway(
        make_registry(entry), client_factory=lambda _entry, _key: FakeClient(completions)
    )

    response = await gateway.generate(make_request())

    assert response.provider_attempt == 2
    assert len(completions.calls) == 2


@pytest.mark.asyncio
async def test_gateway_groups_same_access_route_by_model_vendor() -> None:
    minimax = make_entry(
        "minimax_m3",
        vendor="minimax",
        route="dashscope-evaluation",
        model="MiniMax-M3",
        max_retries=0,
    )
    qwen = make_entry(
        "qwen38_flash",
        vendor="qwen",
        route="dashscope-evaluation",
        model="qwen3.8-flash",
        max_retries=0,
    )
    registry = ModelRegistry(
        backend="openai_compatible",
        active_profile="minimax",
        profiles={"minimax": minimax.entry_id, "qwen": qwen.entry_id},
        entries={minimax.entry_id: minimax, qwen.entry_id: qwen},
        credentials={"test": "test-key"},
    )
    clients = {
        minimax.entry_id: FakeClient(
            FakeCompletions(
                [
                    {
                        "choices": [{"message": {"content": '{"kind":"character_message"}'}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 1},
                    }
                ]
            )
        ),
        qwen.entry_id: FakeClient(
            FakeCompletions(
                [
                    {
                        "choices": [{"message": {"content": '{"kind":"character_message"}'}}],
                        "usage": {"prompt_tokens": 10, "completion_tokens": 1},
                    }
                ]
            )
        ),
    }
    gateway = OpenAICompatibleGateway(
        registry, client_factory=lambda entry, _key: clients[entry.entry_id]
    )

    await gateway.generate(make_request(model_profile="minimax"))
    await gateway.generate(make_request(model_profile="qwen"))

    assert set(gateway.usage_tracker.snapshot()) == {"minimax", "qwen"}


@pytest.mark.asyncio
async def test_gateway_does_not_call_provider_after_deadline() -> None:
    completions = FakeCompletions([])
    gateway = OpenAICompatibleGateway(
        make_registry(make_entry()), client_factory=lambda _entry, _key: FakeClient(completions)
    )

    with pytest.raises(ModelGatewayError) as raised:
        await gateway.generate(make_request(deadline_utc=datetime.now(UTC) - timedelta(seconds=1)))

    assert raised.value.code == "timeout"
    assert completions.calls == []


@pytest.mark.parametrize(
    ("status_code", "expected_code", "retryable"),
    [
        (401, "authentication", False),
        (429, "rate_limited", True),
        (503, "temporary_unavailable", True),
        (400, "invalid_request", False),
    ],
)
def test_provider_errors_are_stable_and_redacted(
    status_code: int, expected_code: str, retryable: bool
) -> None:
    error = classify_provider_error(FakeProviderError(status_code))

    assert error.code == expected_code
    assert error.retryable is retryable
    assert "provider text" not in str(error)
