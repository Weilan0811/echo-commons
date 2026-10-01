import asyncio
from datetime import UTC, datetime, timedelta

import pytest
from test_social_planning import build_planning_system, send

from echo_commons.agents.contracts.output import (
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.agents.contracts.run import AgentRunStatus, AgentStopReason
from echo_commons.agents.harness.context import project_snapshot
from echo_commons.agents.harness.progress import ToolProgressState
from echo_commons.agents.harness.runner import HarnessBackend
from echo_commons.agents.harness.tools import ToolRegistration, ToolRegistry
from echo_commons.infrastructure.models.openai_compatible import OpenAICompatibleGateway
from echo_commons.infrastructure.models.protocol import ToolCall
from echo_commons.infrastructure.models.registry import load_model_registry
from echo_commons.infrastructure.observability.debug_capture import AgentDebugCapture
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.services.registry import AgentRegistry
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.conversations.tasks.execution import (
    ConversationExecution,
    ExecutionLimits,
)
from echo_commons.modules.memory.tools.search import MemorySearchTool, memory_progress
from echo_commons.shared.actors import ActorRef


def prepare_system(tmp_path):
    system = build_planning_system(tmp_path)
    for character, text in (("first", "私有词榆树702"), ("second", "私有词松树903")):
        private_conversation = "private-" + character
        system.conversations.create(
            "community",
            "direct",
            (ActorRef("player", "alice"), ActorRef("character", character)),
            conversation_id=private_conversation,
        )
        system.intake.send("community", private_conversation, PlayerMessage("alice", text, text))
    send(
        system,
        "你还记得我在私聊里告诉你的私有词是什么吗？请查找记忆再告诉我，别猜。",
    )
    system.planner.plan()
    with system.database.read() as connection:
        system.task_ids = tuple(
            row[0]
            for row in connection.execute(
                "SELECT task_id FROM conversation_tasks WHERE conversation_id = 'conversation' "
                "ORDER BY character_id"
            )
        )
    return attach_execution(system, tmp_path)


def attach_execution(system, tmp_path):
    outputs = OutputRegistry()
    outputs.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)
    models = load_model_registry()
    capture = AgentDebugCapture(tmp_path / "capture")
    gateway = OpenAICompatibleGateway(models, debug_capture=capture)
    tool = MemorySearchTool(system.database, system.retrieval)
    tools = (ToolRegistration(tool, memory_progress),)
    backend = HarnessBackend(gateway, outputs=outputs, tools=tools, debug_capture=capture)
    registry = AgentRegistry(
        InstanceRepository(),
        load_blueprint_catalog(),
        backend,
        CapabilityResolver(frozenset({"memory_search"})),
        models.task_routing,
    )
    system.executor = ConversationExecution(
        system.database, system.tasks, registry, ExecutionLimits()
    )
    system.gateway, system.outputs, system.tool_registry = gateway, outputs, ToolRegistry(tools)
    return system


def test_invocation_and_tool_use_persisted_independent_scope(tmp_path):
    system = prepare_system(tmp_path)
    prepared = tuple(system.executor.prepare(task, attempt=1) for task in system.task_ids)
    assert {item.invocation.scope.character_id for item in prepared} == {"first", "second"}

    async def check():
        for item in prepared:
            invocation = item.invocation
            own = "榆树702" if invocation.scope.character_id == "first" else "松树903"
            other = "松树903" if own == "榆树702" else "榆树702"
            assert invocation.context_input.snapshot_id == invocation.context.snapshot_id
            result = await system.tool_registry.execute(
                ToolCall(
                    call_id="scope-check", name="memory_search", arguments={"query": "私有词"}
                ),
                invocation,
            )
            assert result.ok
            texts = " ".join(hit["text"] for hit in result.output["items"])
            assert own in texts and other not in texts
            prompt = project_snapshot(
                invocation.context,
                output_contract=invocation.output_contract,
                outputs=system.outputs,
            )
            assert other not in " ".join(message.content for message in prompt.messages)
            progress = ToolProgressState()
            keys = memory_progress(result)
            assert progress.observe(keys).progressed
            assert not progress.observe(keys).progressed
            invalid = await system.tool_registry.execute(
                ToolCall(
                    call_id="invalid",
                    name="memory_search",
                    arguments={"query": "私有词", "character_id": "second"},
                ),
                invocation,
            )
            assert not invalid.ok and invalid.error_code == "invalid_query"
        with pytest.raises(ValueError, match="does not belong"):
            await prepared[0].agent.run(prepared[1].invocation)
        await system.gateway.close()

    asyncio.run(check())


def test_expired_invocation_stops_before_provider_call(tmp_path):
    system = prepare_system(tmp_path)
    prepared = system.executor.prepare(
        system.task_ids[0], attempt=1, deadline_utc=datetime.now(UTC) - timedelta(seconds=1)
    )
    result = asyncio.run(prepared.agent.run(prepared.invocation))
    assert result.status is AgentRunStatus.RETRYABLE
    assert result.stop_reason is AgentStopReason.DEADLINE_EXCEEDED
    assert result.usage_summary.model_request_count == 0
    assert system.gateway._clients == {}


@pytest.mark.model
def test_two_instances_generate_using_real_model_and_scoped_search(tmp_path):
    system = prepare_system(tmp_path)

    async def run():
        try:
            return await asyncio.gather(
                *(
                    system.executor.execute(
                        task, attempt=1, deadline_utc=datetime.now(UTC) + timedelta(seconds=90)
                    )
                    for task in system.task_ids
                )
            )
        finally:
            await system.gateway.close()

    results = asyncio.run(run())
    assert len(results) == 2
    for task, result in zip(system.task_ids, results, strict=True):
        prepared = system.executor.prepare(task, attempt=1)
        character_id = prepared.invocation.scope.character_id
        assert result.agent_id == prepared.agent.descriptor.agent_id
        assert result.status is AgentRunStatus.COMPLETED, result.model_dump_json()
        assert result.usage_summary.model_request_count >= 2, result.model_dump_json()
        assert result.usage_summary.tool_call_count >= 1
        assert isinstance(result.output.payload, CharacterMessageProposal)
        restored = system.outputs.restore_result(result.model_dump_json())
        assert isinstance(restored.output.payload, CharacterMessageProposal)
        assert restored == result
        content = result.output.payload.utterance
        own = "榆树702" if character_id == "first" else "松树903"
        other = "松树903" if character_id == "first" else "榆树702"
        assert own in content and other not in content
