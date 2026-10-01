from __future__ import annotations

from collections import deque
from uuid import uuid4

import pytest
from support_agent_context import build_test_snapshot

from echo_server.agents.contracts import (
    AgentInvocation,
    AgentRunStatus,
    AgentStopReason,
    ContextInputRef,
    ConversationScope,
    Correlation,
    ExecutionPolicy,
    InvocationIdentity,
    OutputContractRef,
    RecoveryAction,
)
from echo_server.agents.harness import EchoNativeBackend, ToolContext, ToolRegistration, ToolResult
from echo_server.runtime.memory import memory_search_progress_keys
from echo_server.services.model_gateway import FakeModelGateway, ModelResponse


def make_invocation(
    *,
    allowed_tools: tuple[str, ...] = (),
    max_model_steps: int = 4,
    max_model_requests: int = 4,
    max_tool_calls: int = 4,
) -> AgentInvocation:
    context = build_test_snapshot()
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


class ScriptedTool:
    def __init__(self, name: str, results: list[ToolResult]) -> None:
        self.name = name
        self._results = deque(results)

    async def invoke(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        result = self._results.popleft()
        return result.model_copy(update={"call_id": context.call_id, "name": context.tool_name})


def terminal_response() -> ModelResponse:
    return ModelResponse.terminal(
        {
            "thought": "我先想清楚再回答。",
            "utterance": "我在听。",
        }
    )


def progress_keys(result: ToolResult) -> tuple[tuple[str, ...], ...]:
    return tuple((str(item["id"]), str(item["version"])) for item in result.output["items"])


@pytest.mark.asyncio
async def test_control_state_is_nested_and_progress_is_created_per_tool() -> None:
    tool = ScriptedTool(
        "read_notes",
        [ToolResult(call_id="", name="", ok=True, output={"items": []})],
    )
    gateway = FakeModelGateway(
        [ModelResponse.tool_call("read_notes", call_id="notes-1"), terminal_response()]
    )
    harness = EchoNativeBackend(
        gateway,
        agent_id="xiaojin.character",
        tools=(ToolRegistration(tool=tool, progress_extractor=progress_keys),),
    )

    result = await harness.run(
        make_invocation(allowed_tools=("read_notes",), max_model_steps=2, max_model_requests=2)
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.steps[0].tool_activities[0].progressed is False


@pytest.mark.asyncio
async def test_harness_repairs_invalid_output_in_the_same_run() -> None:
    gateway = FakeModelGateway(
        [
            ModelResponse.terminal({"kind": "character_message"}),
            terminal_response(),
        ]
    )
    harness = EchoNativeBackend(gateway, agent_id="xiaojin.character")

    result = await harness.run(make_invocation(max_model_steps=2, max_model_requests=2))

    assert result.status is AgentRunStatus.COMPLETED
    assert result.step_count == 2
    assert result.repair_count == 1
    assert gateway.requests[1].messages[-2].role == "assistant"
    assert gateway.requests[1].messages[-1].role == "user"
    assert "invalid_model_output" in gateway.requests[1].messages[-1].content


@pytest.mark.asyncio
async def test_repeated_invalid_output_fails_after_one_repair() -> None:
    gateway = FakeModelGateway(
        [
            ModelResponse.terminal({"kind": "character_message"}),
            ModelResponse.terminal({"kind": "character_message"}),
        ]
    )
    harness = EchoNativeBackend(gateway, agent_id="xiaojin.character")

    result = await harness.run(make_invocation(max_model_steps=3, max_model_requests=3))

    assert result.status is AgentRunStatus.FAILED
    assert result.stop_reason is AgentStopReason.INVALID_MODEL_OUTPUT
    assert result.recovery is not None
    assert result.recovery.action is RecoveryAction.FAIL
    assert result.repair_count == 1


@pytest.mark.asyncio
async def test_harness_repairs_a_tool_argument_error() -> None:
    tool = ScriptedTool(
        "read_notes",
        [
            ToolResult(call_id="", name="", ok=False, error_code="invalid_query"),
        ],
    )
    gateway = FakeModelGateway(
        [
            ModelResponse.tool_call("read_notes", {"query": ""}, call_id="notes-1"),
            terminal_response(),
        ]
    )
    harness = EchoNativeBackend(
        gateway,
        agent_id="xiaojin.character",
        tools=(ToolRegistration(tool=tool),),
    )

    result = await harness.run(
        make_invocation(allowed_tools=("read_notes",), max_model_steps=2, max_model_requests=2)
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.repair_count == 1
    assert "invalid_query" in gateway.requests[1].messages[-1].content


@pytest.mark.asyncio
async def test_retryable_tool_error_returns_task_recovery() -> None:
    tool = ScriptedTool(
        "read_notes",
        [ToolResult(call_id="", name="", ok=False, error_code="memory_search_failed")],
    )
    gateway = FakeModelGateway([ModelResponse.tool_call("read_notes", call_id="notes-1")])
    harness = EchoNativeBackend(
        gateway,
        agent_id="xiaojin.character",
        tools=(ToolRegistration(tool=tool),),
    )

    result = await harness.run(
        make_invocation(allowed_tools=("read_notes",), max_model_steps=2, max_model_requests=2)
    )

    assert result.status is AgentRunStatus.RETRYABLE
    assert result.stop_reason is AgentStopReason.TOOL_ERROR
    assert result.recovery is not None
    assert result.recovery.action is RecoveryAction.RETRY_TASK
    assert result.recovery.code == "memory_search_failed"


@pytest.mark.asyncio
async def test_repeated_memory_sources_disable_only_that_tool() -> None:
    result_item = {"sourceId": "memory-1", "contentVersion": "v1"}
    tool = ScriptedTool(
        "memory_search",
        [
            ToolResult(call_id="", name="", ok=True, output={"results": [result_item]}),
            ToolResult(call_id="", name="", ok=True, output={"results": [result_item]}),
            ToolResult(call_id="", name="", ok=True, output={"results": [result_item]}),
        ],
    )
    gateway = FakeModelGateway(
        [
            ModelResponse.tool_call("memory_search", call_id="memory-1"),
            ModelResponse.tool_call("memory_search", call_id="memory-2"),
            ModelResponse.tool_call("memory_search", call_id="memory-3"),
            terminal_response(),
        ]
    )
    harness = EchoNativeBackend(
        gateway,
        agent_id="xiaojin.character",
        tools=(
            ToolRegistration(
                tool=tool,
                progress_extractor=memory_search_progress_keys,
                no_progress_limit=2,
            ),
        ),
    )

    result = await harness.run(
        make_invocation(
            allowed_tools=("memory_search",),
            max_model_steps=4,
            max_model_requests=4,
            max_tool_calls=3,
        )
    )

    assert result.status is AgentRunStatus.COMPLETED
    activities = [step.tool_activities[0] for step in result.steps[:3]]
    assert [activity.progressed for activity in activities] == [True, False, False]
    assert [activity.no_progress_streak for activity in activities] == [0, 1, 2]
    assert gateway.requests[3].allowed_tools == ()
    assert gateway.requests[3].tool_definitions == ()


@pytest.mark.asyncio
async def test_new_memory_source_resets_the_no_progress_streak() -> None:
    tool = ScriptedTool(
        "memory_search",
        [
            ToolResult(
                call_id="",
                name="",
                ok=True,
                output={"results": [{"sourceId": "memory-1", "contentVersion": "v1"}]},
            ),
            ToolResult(
                call_id="",
                name="",
                ok=True,
                output={"results": [{"sourceId": "memory-1", "contentVersion": "v1"}]},
            ),
            ToolResult(
                call_id="",
                name="",
                ok=True,
                output={"results": [{"sourceId": "memory-2", "contentVersion": "v1"}]},
            ),
        ],
    )
    gateway = FakeModelGateway(
        [
            ModelResponse.tool_call("memory_search", call_id="memory-1"),
            ModelResponse.tool_call("memory_search", call_id="memory-2"),
            ModelResponse.tool_call("memory_search", call_id="memory-3"),
            terminal_response(),
        ]
    )
    harness = EchoNativeBackend(
        gateway,
        agent_id="xiaojin.character",
        tools=(
            ToolRegistration(
                tool=tool,
                progress_extractor=memory_search_progress_keys,
                no_progress_limit=2,
            ),
        ),
    )

    result = await harness.run(
        make_invocation(
            allowed_tools=("memory_search",),
            max_model_steps=4,
            max_model_requests=4,
            max_tool_calls=3,
        )
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.steps[1].tool_activities[0].no_progress_streak == 1
    assert result.steps[2].tool_activities[0].progressed is True
    assert gateway.requests[3].allowed_tools == ("memory_search",)


@pytest.mark.asyncio
async def test_tool_budget_failure_keeps_completed_tool_activity() -> None:
    tool = ScriptedTool(
        "read_notes",
        [
            ToolResult(call_id="", name="", ok=True, output={"found": True}),
        ],
    )
    gateway = FakeModelGateway(
        [
            ModelResponse(
                kind="tool_call",
                tool_calls=(
                    {"call_id": "notes-1", "name": "read_notes", "arguments": {}},
                    {"call_id": "notes-2", "name": "read_notes", "arguments": {}},
                ),
            )
        ]
    )
    harness = EchoNativeBackend(
        gateway,
        agent_id="xiaojin.character",
        tools=(ToolRegistration(tool=tool),),
    )

    result = await harness.run(
        make_invocation(
            allowed_tools=("read_notes",),
            max_model_steps=2,
            max_model_requests=2,
            max_tool_calls=1,
        )
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.stop_reason is AgentStopReason.BUDGET_EXHAUSTED
    assert result.usage_summary.tool_call_count == 1
    assert [activity.error_code for activity in result.steps[0].tool_activities] == [
        None,
        "tool_budget_exhausted",
    ]


@pytest.mark.asyncio
async def test_model_step_budget_is_distinct_from_tool_budget() -> None:
    tool = ScriptedTool(
        "read_notes",
        [ToolResult(call_id="", name="", ok=True, output={"found": True})],
    )
    gateway = FakeModelGateway([ModelResponse.tool_call("read_notes", call_id="notes-1")])
    harness = EchoNativeBackend(
        gateway,
        agent_id="xiaojin.character",
        tools=(ToolRegistration(tool=tool),),
    )

    result = await harness.run(
        make_invocation(
            allowed_tools=("read_notes",),
            max_model_steps=1,
            max_model_requests=2,
            max_tool_calls=1,
        )
    )

    assert result.status is AgentRunStatus.FAILED
    assert result.stop_reason is AgentStopReason.BUDGET_EXHAUSTED
    assert result.diagnostic_codes == ("model_step_budget_exhausted",)
