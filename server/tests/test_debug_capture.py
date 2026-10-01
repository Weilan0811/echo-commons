from __future__ import annotations

import json
from datetime import UTC, datetime
from pathlib import Path
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
    InvocationIdentity,
    OutputContractRef,
)
from echo_server.agents.harness import EchoNativeBackend
from echo_server.config import Settings, load_settings
from echo_server.observability.debug_capture import AgentDebugCapture
from echo_server.services.model_gateway import (
    FakeModelGateway,
    ModelEntry,
    ModelRegistry,
    ModelRequest,
    ModelResponse,
    OpenAICompatibleGateway,
    PromptMessage,
)


class FakeCompletions:
    def __init__(self, response: object) -> None:
        self.response = response

    async def create(self, **_: object) -> object:
        return self.response


def _entry() -> ModelEntry:
    return ModelEntry(
        entry_id="test-entry",
        model_vendor="test-provider",
        model="test-model",
        base_url="https://example.test/v1",
        credential_ref="test",
        access_route="test-route",
        max_retries=0,
    )


def _request() -> ModelRequest:
    return ModelRequest(
        invocation_id=uuid4(),
        trace_id=uuid4(),
        agent_id="xiaojin.character",
        model_profile="light",
        attempt=1,
        step_index=1,
        messages=(
            PromptMessage(role="system", content="完整的系统上下文"),
            PromptMessage(role="user", content="玩家输入"),
        ),
        output_schema="character_message.v2",
    )


def _invocation() -> AgentInvocation:
    now = datetime(2026, 9, 10, 12, 0, tzinfo=UTC)
    snapshot = build_test_snapshot(
        player_text="玩家输入",
        context_version="context-1",
        now_utc=now,
        baseline_resource_id="default-chat",
        baseline_content="聊天基线",
        baseline_version="1",
        profile_content="小槿身份",
        profile_version="1",
    )
    return AgentInvocation(
        identity=InvocationIdentity(agent_id="xiaojin.character"),
        scope=ConversationScope(
            conversation_id=snapshot.conversation_id,
            character_id=snapshot.character_id,
        ),
        context=snapshot,
        context_input=ContextInputRef(
            snapshot_id=snapshot.context_version,
            snapshot_schema_version=snapshot.snapshot_version,
            snapshot_fingerprint=snapshot.input_fingerprint,
        ),
        output_contract=OutputContractRef(kind="character_message", version="v2"),
        execution_policy=ExecutionPolicy(),
        correlation=Correlation(task_id=uuid4(), trace_id=uuid4()),
    )


def test_debug_capture_requires_explicit_non_production_opt_in(tmp_path) -> None:
    assert AgentDebugCapture.from_settings(Settings()) is None
    assert (
        AgentDebugCapture.from_settings(
            Settings(
                environment="production",
                debug_capture_enabled=True,
                debug_capture_path=str(tmp_path),
            )
        )
        is None
    )

    capture = AgentDebugCapture.from_settings(
        Settings(debug_capture_enabled=True, debug_capture_path=str(tmp_path))
    )

    assert capture is not None
    assert capture.directory.parent == tmp_path.resolve()


def test_load_settings_reads_debug_capture_config(tmp_path) -> None:
    source = Path(__file__).parents[1] / "config" / "settings.toml"
    config = tmp_path / "settings.toml"
    content = source.read_text(encoding="utf-8")
    content = content.replace("debug_capture_enabled = false", "debug_capture_enabled = true")
    content = content.replace(
        'debug_capture_path = "../data/debug-captures"',
        'debug_capture_path = "debug"',
    )
    config.write_text(content, encoding="utf-8")

    settings = load_settings(config)

    assert settings.debug_capture_enabled is True
    assert settings.debug_capture_path == str(tmp_path / "debug")


@pytest.mark.asyncio
async def test_gateway_capture_keeps_full_invalid_provider_response(tmp_path) -> None:
    raw_response = {
        "id": "provider-response-1",
        "model": "test-model",
        "choices": [
            {
                "finish_reason": "stop",
                "message": {
                    "role": "assistant",
                    "content": "不是 JSON，导致解析失败",
                },
            }
        ],
        "usage": {"prompt_tokens": 17, "completion_tokens": 8},
    }
    completions = FakeCompletions(raw_response)
    entry = _entry()
    registry = ModelRegistry(
        backend="openai_compatible",
        active_profile="light",
        profiles={"light": entry.entry_id},
        entries={entry.entry_id: entry},
        credentials={"test": "test-key"},
    )
    capture = AgentDebugCapture(tmp_path / "captures")
    gateway = OpenAICompatibleGateway(
        registry,
        client_factory=lambda _entry, _key: SimpleNamespace(
            chat=SimpleNamespace(completions=completions)
        ),
        debug_capture=capture,
    )

    response = await gateway.generate(_request())

    assert response.kind.value == "invalid"
    documents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in capture.directory.glob("*-model_call.json")
    ]
    assert len(documents) == 1
    document = documents[0]
    assert document["input"]["modelRequest"]["messages"][0]["content"] == "完整的系统上下文"
    assert document["input"]["modelRequest"]["messages"][1]["content"] == "玩家输入"
    assert document["input"]["providerRequest"]["response_format"] == {"type": "json_object"}
    assert document["output"]["rawProviderResponse"] == raw_response
    assert document["output"]["normalizedModelResponse"]["kind"] == "invalid"


@pytest.mark.asyncio
async def test_agent_capture_pairs_invocation_and_final_run_result(tmp_path) -> None:
    capture = AgentDebugCapture(tmp_path / "captures")
    harness = EchoNativeBackend(
        FakeModelGateway(
            [
                ModelResponse.terminal(
                    {
                        "thought": "我想温和地回应。",
                        "utterance": "完整的角色回复",
                    }
                )
            ]
        ),
        agent_id="xiaojin.character",
        debug_capture=capture,
    )

    result = await harness.run(_invocation())

    assert result.status is AgentRunStatus.COMPLETED
    documents = [
        json.loads(path.read_text(encoding="utf-8"))
        for path in capture.directory.glob("*.json")
        if path.name != "session.json"
    ]
    assert [document["eventType"] for document in documents] == [
        "agent_run.started",
        "agent_run.completed",
    ]
    started, completed = documents
    assert (
        started["input"]["invocation"]["context"]["request"]["trigger_message"]["text"]
        == "玩家输入"
    )
    assert (
        completed["output"]["agentRunResult"]["output"]["proposal"]["payload"]["utterance"]
        == "完整的角色回复"
    )
