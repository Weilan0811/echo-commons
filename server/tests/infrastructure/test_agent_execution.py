import asyncio
import json
from datetime import UTC, datetime, timedelta

import pytest
from recovery_support import conversation_recovery
from test_application_lifecycle import settings_for
from test_social_planning import build_planning_system, send

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.execution import ExecutionLimits
from echo_commons.agents.contracts.invocation import InvocationPurpose
from echo_commons.agents.contracts.output import (
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.agents.contracts.run import AgentRunStatus, AgentStopReason
from echo_commons.agents.harness.progress import ToolProgressState
from echo_commons.agents.harness.runner import HarnessBackend
from echo_commons.agents.harness.tools import ToolRegistration, ToolRegistry
from echo_commons.infrastructure.models.openai_compatible import OpenAICompatibleGateway
from echo_commons.infrastructure.models.protocol import ToolCall
from echo_commons.infrastructure.models.registry import load_model_registry
from echo_commons.infrastructure.observability.debug_capture import AgentDebugCapture
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.services.registry import AgentPurposeBinding, AgentRegistry
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.conversations.tasks.execution import (
    ConversationExecution,
)
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.modules.memory.services.retrieval import SearchScope
from echo_commons.modules.memory.tools.search import MemorySearchTool, memory_progress
from echo_commons.shared.actors import ActorRef


def prepare_system(tmp_path, *, lookup_text=None, mentions=()):
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
        lookup_text or "你还记得我在私聊里告诉你的私有词是什么吗？请查找记忆再告诉我，别猜。",
        mentions=mentions,
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


@pytest.mark.model
def test_mentioned_characters_make_legal_memory_choices_using_real_model(tmp_path):
    system = prepare_system(
        tmp_path,
        lookup_text="请两位小槿分别调用 memory_search 查询‘私有词’，告诉我私聊里各自收到的词。",
        mentions=(ActorRef("character", "first"), ActorRef("character", "second")),
    )

    async def run():
        prepared = tuple(system.executor.prepare(task, attempt=1) for task in system.task_ids)
        try:
            return await asyncio.gather(*(item.agent.run(item.invocation) for item in prepared))
        finally:
            await system.gateway.close()

    results = asyncio.run(run())
    for task, result in zip(system.task_ids, results, strict=True):
        assert_legal_memory_result(system, task, result)


def attach_execution(system, tmp_path):
    outputs = OutputRegistry()
    outputs.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)
    settings = settings_for(tmp_path, workers=False)
    models = load_model_registry(settings.model_registry_path, settings.model_secrets_path)
    capture = AgentDebugCapture(tmp_path / "capture")
    gateway = OpenAICompatibleGateway(models, debug_capture=capture)
    tool = MemorySearchTool(system.database, system.retrieval, max_results=5)
    tools = (ToolRegistration(tool, memory_progress),)
    backend = HarnessBackend(
        gateway, outputs=outputs, projector=project_snapshot, tools=tools, debug_capture=capture
    )
    registry = AgentRegistry(
        InstanceRepository(),
        load_blueprint_catalog(),
        {
            InvocationPurpose.CONVERSATION_REPLY: AgentPurposeBinding(
                backend, (CHARACTER_MESSAGE_CONTRACT,)
            )
        },
        CapabilityResolver(frozenset({"memory_search"})),
        models.task_routing,
    )
    system.executor = ConversationExecution(
        system.database, system.tasks, registry, ExecutionLimits(), conversation_recovery(system)
    )
    system.gateway, system.outputs, system.tool_registry = gateway, outputs, ToolRegistry(tools)
    system.capture = capture
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
            texts = " ".join(hit["summary"] for hit in result.output["results"])
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
            limited = ToolRegistry(
                (MemorySearchTool(system.database, system.retrieval, max_results=1),)
            )
            parameters = limited.definitions(("memory_search",))[0]["function"]["parameters"]
            assert parameters["properties"]["limit"]["maximum"] == 1
            narrowed = await limited.execute(
                ToolCall(call_id="limited", name="memory_search", arguments={"query": "私有词"}),
                invocation,
            )
            assert narrowed.ok and len(narrowed.output["results"]) == 1
            oversized = await limited.execute(
                ToolCall(
                    call_id="oversized",
                    name="memory_search",
                    arguments={"query": "私有词", "limit": 2},
                ),
                invocation,
            )
            assert not oversized.ok and oversized.error_code == "invalid_limit"
        with pytest.raises(ExecutionError, match="invocation_identity_mismatch"):
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
def test_two_instances_make_independent_memory_choices_using_real_model(tmp_path):
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
        assert_legal_memory_result(system, task, result)


def assert_legal_memory_result(system, task, result):
    prepared = system.executor.prepare(task, attempt=1)
    invocation = prepared.invocation
    other = "松树903" if invocation.scope.character_id == "first" else "榆树702"
    assert result.agent_id == prepared.agent.descriptor.agent_id
    assert result.usage_summary.model_request_count >= 1
    assert result.status in {AgentRunStatus.COMPLETED, AgentRunStatus.NO_PROPOSAL}, (
        result.model_dump_json()
    )
    if result.status is AgentRunStatus.COMPLETED:
        assert result.stop_reason is AgentStopReason.PROPOSAL_READY
        assert isinstance(result.output.payload, CharacterMessageProposal)
        assert result.output.payload.utterance.strip()
        assert other not in result.output.model_dump_json()
    else:
        assert result.stop_reason is AgentStopReason.NO_MOTIVATION
        assert result.output is None
    assert system.outputs.restore_result(result.model_dump_json()) == result
    activities = {
        activity.call_id: activity for step in result.steps for activity in step.tool_activities
    }
    observations = {}
    calls = {}
    for path in system.capture.directory.glob("*-model_call.json"):
        capture = json.loads(path.read_text(encoding="utf-8"))
        if capture["correlation"]["invocationId"] != str(result.invocation_id):
            continue
        response = capture["output"]["normalizedModelResponse"]
        if response:
            for call in response["tool_calls"]:
                calls[call["call_id"]] = call
        for message in capture["input"]["modelRequest"]["messages"]:
            if message["role"] == "tool":
                observation = json.loads(message["content"])
                observations[observation["callId"]] = observation
    policy = invocation.context.read_policy
    scope = SearchScope(
        invocation.scope.community_id,
        invocation.scope.character_id,
        policy.observed_at_utc,
        policy.conversation_id,
        policy.upper_sequence,
    )
    with system.database.read() as connection:
        sources = system.retrieval.sources(connection, scope)
        for call_id, activity in activities.items():
            assert activity.name == "memory_search"
            assert calls[call_id]["name"] == "memory_search"
            if not activity.ok:
                assert activity.error_code
                continue
            observation = observations[call_id]
            assert observation["ok"]
            assert "character_id" not in calls[call_id]["arguments"]
            for hit in observation["output"]["results"]:
                source = sources[(hit["sourceKind"], hit["sourceId"])]
                assert hit["contentVersion"] == source.source_version
                assert hit["summary"] == source.text
                assert other not in hit["summary"]
