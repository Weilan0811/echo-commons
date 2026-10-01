from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from support_agent_context import build_test_snapshot

from echo_server.agents.contracts import (
    PROMPT_LAYOUT_VERSION,
    AgentInvocation,
    AgentRunStatus,
    AgentStopReason,
    ContextInputRef,
    ConversationScope,
    Correlation,
    ExecutionPolicy,
    InvocationIdentity,
    MemoryContext,
    MemoryItem,
    OutputContractRef,
    UsageSummary,
)
from echo_server.agents.harness import EchoNativeBackend, ToolContext, ToolResult
from echo_server.agents.harness.context import (
    CHARACTER_MESSAGE_OUTPUT_SCHEMA,
    CHARACTER_MESSAGE_OUTPUT_SCHEMA_TEMPLATE,
    project_snapshot,
)
from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.domain.conversation import ConversationParticipant
from echo_server.domain.messages import SubmitMessageCommand, SyncMessagesQuery
from echo_server.domain.state import CharacterAvailabilityStatus, CharacterState, WorldState
from echo_server.runtime.application_runtime import ApplicationRuntime
from echo_server.runtime.conversation_worker import ConversationWorker
from echo_server.services.model_gateway import FakeModelGateway, ModelResponse
from echo_server.store.database import Database


def make_invocation(
    *,
    allowed_tools: tuple[str, ...] = (),
    max_model_steps: int = 1,
    max_model_requests: int | None = None,
    max_tool_calls: int = 0,
) -> AgentInvocation:
    context = build_test_snapshot(stage_summary="初识")
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
        execution_policy=ExecutionPolicy(
            allowed_tools=allowed_tools,
            max_model_steps=max_model_steps,
            max_model_requests=max_model_requests,
            max_tool_calls=max_tool_calls,
        ),
        correlation=Correlation(task_id=uuid4(), trace_id=uuid4()),
    )


def test_harness_projects_identity_with_a_fixed_versioned_layout():
    invocation = make_invocation()

    prompt = project_snapshot(
        invocation.context,
        output_contract=invocation.output_contract,
    )

    assert prompt.baseline_version == "v1"
    assert prompt.identity_version == "v1"
    assert prompt.prompt_layout_version == PROMPT_LAYOUT_VERSION
    assert prompt.context_snapshot_version == 2
    assert prompt.output_schema == CHARACTER_MESSAGE_OUTPUT_SCHEMA
    assert [message.role for message in prompt.messages] == ["system", "user"]
    assert CHARACTER_MESSAGE_OUTPUT_SCHEMA_TEMPLATE in prompt.messages[0].content
    prompt_text = prompt.messages[0].content
    assert prompt_text.startswith("<response_contract>")
    assert "对象只能包含 thought 和 utterance 两个字段" in prompt_text
    assert "换行只表示真实停顿或本来会分开的说话" in prompt_text
    assert "没有需要展开时，短短回一句也足够" in prompt_text
    assert "thought 是角色随手留下的私有内心" in prompt_text
    assert "本次只说明这条角色回复的表达方式" not in prompt_text
    assert "<conversation_guidance>" in prompt_text
    assert "角色设定只是你生活的底色" in prompt_text
    assert "<agent_contract>" in prompt_text
    assert "<character_profile>" in prompt_text
    assert "<character_relational_dynamics>" not in prompt_text
    assert "<character_voice>" not in prompt_text
    assert "output_schema=" not in prompt_text
    assert "baseline content" in prompt_text
    assert "identity content" in prompt_text
    assert "<relationship_state>" in prompt_text
    assert "你和对方目前还是陌生人。" in prompt_text
    assert "初识" not in "\n".join(message.content for message in prompt.messages)
    assert prompt.messages[-1].role == "user"
    assert prompt.messages[-1].content == "hello"


def test_v2_prompt_places_memory_state_and_relationship_before_history():
    snapshot = build_test_snapshot()
    snapshot = snapshot.model_copy(
        update={
            "character_state": snapshot.character_state.model_copy(update={"mood": "平常"}),
            "memory_context": MemoryContext(
                core_memory=MemoryItem(
                    memory_id="core-1",
                    summary="核心记忆内容",
                )
            ),
        }
    )
    prompt = project_snapshot(
        snapshot,
        output_contract=OutputContractRef(kind="character_message", version="v2"),
    )

    system_text = prompt.messages[0].content
    assert system_text.index("<core_memory>") < system_text.index("<current_state>")
    assert system_text.index("<current_state>") < system_text.index("<relationship_state>")
    assert system_text.index("<relationship_state>") < system_text.index("<conversation_history>")
    assert all(message.role != "system" for message in prompt.messages[1:])
    assert prompt.messages[-1].role == "user"


@pytest.mark.asyncio
async def test_harness_completes_a_terminal_proposal():
    gateway = FakeModelGateway(
        [
            ModelResponse.terminal(
                {
                    "thought": "先听听对方想说什么。",
                    "utterance": "我在听。",
                },
                usage_summary=UsageSummary(input_tokens=3, output_tokens=2, total_tokens=5),
            )
        ]
    )
    harness = EchoNativeBackend(gateway, agent_id="xiaojin.character")
    invocation = make_invocation()

    result = await harness.run(invocation)

    assert result.status is AgentRunStatus.COMPLETED
    assert result.stop_reason is AgentStopReason.PROPOSAL_READY
    assert result.step_count == 1
    assert result.output is not None
    assert result.output.proposal.payload.utterance == "我在听。"
    assert result.output.proposal.payload.thought == "先听听对方想说什么。"
    assert result.output.contract.version == "v2"
    assert result.output.proposal.payload.character_id == "xiaojin"
    assert (
        result.output.proposal.payload.reply_to_message_id
        == invocation.context.trigger_message.message_id
    )
    assert result.usage_summary.model_request_count == 1
    assert gateway.requests[0].step_index == 1
    assert gateway.requests[0].output_schema == CHARACTER_MESSAGE_OUTPUT_SCHEMA


class ReadMemoryTool:
    name = "read_memory"

    async def invoke(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        assert arguments == {"topic": "雨"}
        return ToolResult(
            call_id=context.call_id,
            name=context.tool_name,
            ok=True,
            output={"found": True},
        )


@pytest.mark.asyncio
async def test_harness_loops_through_tool_observation_before_terminal_proposal():
    gateway = FakeModelGateway(
        [
            ModelResponse.tool_call(
                "read_memory",
                {"topic": "雨"},
                call_id="memory-1",
            ),
            ModelResponse.terminal(
                {
                    "thought": "那场雨还留在我心里。",
                    "utterance": "我记得那场雨。",
                }
            ),
        ]
    )
    harness = EchoNativeBackend(
        gateway,
        agent_id="xiaojin.character",
        tools=(ReadMemoryTool(),),
    )
    invocation = make_invocation(
        allowed_tools=("read_memory",),
        max_model_steps=2,
        max_model_requests=2,
        max_tool_calls=1,
    )

    result = await harness.run(invocation)

    assert result.status is AgentRunStatus.COMPLETED
    assert result.step_count == 2
    assert result.usage_summary.model_request_count == 2
    assert result.usage_summary.tool_call_count == 1
    assert result.output is not None
    assert result.output.proposal.payload.utterance == "我记得那场雨。"
    assert gateway.requests[0].tool_definitions[0]["function"]["name"] == "read_memory"
    assert gateway.requests[1].messages[-2].role == "assistant"
    assert gateway.requests[1].messages[-2].metadata["tool_calls"][0]["id"] == "memory-1"
    assert gateway.requests[1].messages[-1].role == "tool"
    assert gateway.requests[1].messages[-1].content.find('"found":true') >= 0


@pytest.mark.asyncio
async def test_harness_fails_closed_when_model_requests_an_unauthorized_tool():
    gateway = FakeModelGateway([ModelResponse.tool_call("write_state")])
    harness = EchoNativeBackend(gateway, agent_id="xiaojin.character")

    result = await harness.run(make_invocation())

    assert result.status is AgentRunStatus.FAILED
    assert result.stop_reason is AgentStopReason.TOOL_NOT_ALLOWED
    assert result.diagnostic_codes == ("tool_not_allowed",)
    assert result.output is None


@pytest.mark.asyncio
async def test_harness_reports_budget_exhaustion_after_a_tool_step():
    gateway = FakeModelGateway([ModelResponse.tool_call("read_memory", {"topic": "雨"})])
    harness = EchoNativeBackend(
        gateway,
        agent_id="xiaojin.character",
        tools=(ReadMemoryTool(),),
    )

    result = await harness.run(
        make_invocation(
            allowed_tools=("read_memory",),
            max_model_steps=1,
            max_model_requests=1,
            max_tool_calls=1,
        )
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.stop_reason is AgentStopReason.BUDGET_EXHAUSTED
    assert result.step_count == 1
    assert result.usage_summary.tool_call_count == 1
    assert result.diagnostic_codes == ("model_step_budget_exhausted",)


@pytest.mark.asyncio
async def test_harness_repairs_invalid_terminal_output_in_the_same_run():
    gateway = FakeModelGateway(
        [
            ModelResponse.terminal({"kind": "character_message", "character_id": "xiaojin"}),
            ModelResponse.terminal(
                {
                    "thought": "我重新想了一下。",
                    "utterance": "我在听。",
                }
            ),
        ]
    )
    harness = EchoNativeBackend(gateway, agent_id="xiaojin.character")

    result = await harness.run(make_invocation(max_model_steps=2, max_model_requests=2))

    assert result.status is AgentRunStatus.COMPLETED
    assert result.stop_reason is AgentStopReason.PROPOSAL_READY
    assert result.repair_count == 1
    assert result.step_count == 2


@pytest.mark.asyncio
async def test_harness_does_not_call_gateway_after_invocation_deadline():
    gateway = FakeModelGateway(
        [
            ModelResponse.terminal(
                {
                    "thought": "这次不该有回复。",
                    "utterance": "不应生成",
                }
            )
        ]
    )
    harness = EchoNativeBackend(gateway, agent_id="xiaojin.character")
    invocation = make_invocation().model_copy(
        update={
            "execution_policy": make_invocation().execution_policy.model_copy(
                update={"deadline_utc": datetime.now(UTC) - timedelta(seconds=1)}
            )
        }
    )

    result = await harness.run(invocation)

    assert result.status is AgentRunStatus.RETRYABLE
    assert result.stop_reason is AgentStopReason.DEADLINE_EXCEEDED
    assert gateway.requests == []


@pytest.mark.asyncio
async def test_stub_agent_implements_the_canonical_run_boundary():
    invocation = make_invocation()
    agent = StubCharacterAgent({"xiaojin": "测试回复"})

    result = await agent.run(invocation)

    assert result.status is AgentRunStatus.COMPLETED
    assert result.harness_version == "stub-v1"
    assert result.output is not None
    assert result.output.proposal.kind == "character_message"
    assert result.output.proposal.payload.utterance == "测试回复"


@pytest.mark.asyncio
async def test_runtime_accepts_a_new_harness_run_without_bypassing_review(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        worker_enabled=False,
        retry_backoff_seconds=0,
    )
    now = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)
    clock = [now]
    harness = EchoNativeBackend(
        FakeModelGateway(
            [
                ModelResponse.terminal(
                    {
                        "thought": "我想认真接住这句话。",
                        "utterance": "来自 Harness。",
                    }
                )
            ]
        ),
        agent_id="stub-harness-character",
        clock=lambda: clock[0],
    )
    runtime = ApplicationRuntime(Database(settings.database_path), harness, settings)
    runtime.clock = lambda: clock[0]
    await runtime.start()
    try:
        async with runtime.database.transaction(immediate=True) as connection:
            await runtime.world_states.save(
                WorldState(state_version=0, world_time_utc=now, updated_at_utc=now),
                connection=connection,
            )
            await runtime.character_states.save(
                CharacterState(
                    character_id=settings.default_character_id,
                    availability_status=CharacterAvailabilityStatus.AVAILABLE,
                    state_version=0,
                    updated_at_utc=now,
                ),
                connection=connection,
            )
            await runtime.participants.save(
                ConversationParticipant(
                    conversation_id=settings.default_conversation_id,
                    character_id=settings.default_character_id,
                    joined_at_utc=now,
                ),
                account_id=settings.account_id,
                connection=connection,
            )
        await runtime.submit_message(
            SubmitMessageCommand(
                account_id=settings.account_id,
                conversation_id=settings.default_conversation_id,
                player_text="hello",
                images=(),
                client_msg_id=uuid4(),
                local_timestamp=now,
            )
        )
        clock[0] = now + timedelta(seconds=6)
        worker = ConversationWorker(runtime, settings)
        assert await worker.run_once() is True
        batch = await runtime.sync_messages(SyncMessagesQuery(settings.account_id))
        assert [message.text for message in batch.messages] == ["hello", "来自 Harness。"]
    finally:
        await runtime.stop()
