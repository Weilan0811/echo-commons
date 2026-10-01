from __future__ import annotations

import json
import os
from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import pytest
from support_xiaojin import (
    IDENTITY_ROOT,
    assert_xiaojin_output_clean,
    build_xiaojin_invocation,
    build_xiaojin_snapshot,
    load_xiaojin_fixture_turns,
    load_xiaojin_forbidden_patterns,
)

from echo_server.agents.character import CharacterAgent, CharacterAgentInvocationError
from echo_server.agents.contracts import AgentRunStatus, AgentStopReason, OutputContractRef
from echo_server.agents.factory import build_default_character_agent
from echo_server.agents.harness import EchoNativeBackend, project_snapshot
from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings, load_settings
from echo_server.services.identity import load_identity_catalog
from echo_server.services.model_gateway import (
    FakeModelGateway,
    ModelResponse,
    resolve_agent_route,
)


def test_factory_without_credentials_still_returns_the_bound_character_boundary(
    tmp_path: Path,
) -> None:
    agent = build_default_character_agent(
        Settings(model_secrets_path=str(tmp_path / "missing-model-secrets.toml"))
    )

    assert isinstance(agent, CharacterAgent)
    assert isinstance(agent.backend, StubCharacterAgent)
    assert agent.agent_id == "xiaojin.character"
    assert agent.character_id == "xiaojin"


def test_v2_character_history_uses_the_structured_output_envelope() -> None:
    catalog = load_identity_catalog(IDENTITY_ROOT)
    turns = [turn for turn in load_xiaojin_fixture_turns() if turn.scenario_id == "idle_l2"]
    first, second = turns[:2]
    first_snapshot = build_xiaojin_snapshot(catalog, first)
    second_snapshot = build_xiaojin_snapshot(catalog, second)
    history_assistant = first_snapshot.trigger_message.model_copy(
        update={
            "message_id": uuid4(),
            "sender_type": "character",
            "sender_id": "xiaojin",
            "text": "上一轮已经展示给玩家的自然语言回复",
            "thought": "上一轮没有展示给玩家的内心记录",
        }
    )
    continuity = second_snapshot.conversation_continuity.model_copy(
        update={
            "session_digest": None,
            "recent_tail": (first_snapshot.trigger_message, history_assistant),
        }
    )
    snapshot = second_snapshot.model_copy(update={"conversation_continuity": continuity})

    prompt = project_snapshot(
        snapshot,
        output_contract=OutputContractRef(kind="character_message", version="v2"),
    )
    system_text = prompt.messages[0].content
    assert system_text.index("<agent_contract>") < system_text.index("<character_profile>")
    assert system_text.index("<character_profile>") < system_text.index(
        "<character_relational_dynamics>"
    )
    assert system_text.index("<character_relational_dynamics>") < system_text.index(
        "<character_voice>"
    )
    assert system_text.index("<character_voice>") < system_text.index("<current_state>")
    assert system_text.index("<current_state>") < system_text.index("<relationship_state>")
    assert system_text.index("<relationship_state>") < system_text.index("<continuity_memory>")
    assert system_text.index("<continuity_memory>") < system_text.index("<conversation_history>")
    assert all(message.role != "system" for message in prompt.messages[1:])
    assert prompt.messages[-1].role == "user"
    assistant_messages = [message for message in prompt.messages if message.role == "assistant"]

    assert len(assistant_messages) == 1
    assert json.loads(assistant_messages[0].content) == {
        "thought": "上一轮没有展示给玩家的内心记录",
        "utterance": "上一轮已经展示给玩家的自然语言回复",
    }

    history_without_thought = history_assistant.model_copy(update={"thought": None})
    continuity = continuity.model_copy(
        update={"recent_tail": (first_snapshot.trigger_message, history_without_thought)}
    )
    snapshot = snapshot.model_copy(update={"conversation_continuity": continuity})
    prompt = project_snapshot(
        snapshot,
        output_contract=OutputContractRef(kind="character_message", version="v2"),
    )
    assistant_messages = [message for message in prompt.messages if message.role == "assistant"]
    assert assistant_messages[0].content == "上一轮已经展示给玩家的自然语言回复"


def test_v2_prompt_keeps_runtime_metadata_and_action_catalog_out_of_model_text() -> None:
    catalog = load_identity_catalog(IDENTITY_ROOT)
    turn = next(turn for turn in load_xiaojin_fixture_turns() if turn.scenario_id == "idle_l2")
    snapshot = build_xiaojin_snapshot(catalog, turn)
    prompt = project_snapshot(
        snapshot,
        output_contract=OutputContractRef(kind="character_message", version="v2"),
        tool_definitions=(
            {
                "type": "function",
                "function": {
                    "name": "memory_search",
                    "description": "读取相关记忆",
                    "parameters": {"type": "object"},
                },
            },
        ),
    )
    model_text = "\n".join(message.content for message in prompt.messages)

    for marker in (
        "resource_id=",
        "content_version=",
        "character_id=xiaojin",
        "context_version",
        "prompt_layout_version",
        "digest_id=",
        "covers_through_sequence=",
        "output_schema=",
        "schema_template=",
        "memory_search",
        "[respond_naturally]",
        "availability=",
        "mood=",
        "physical_condition=",
        "current_activity=",
        "relationship_type=",
        "affection=",
        "trust=",
        "attachment=",
        "world_phase=",
        "独奏期",
        "眼下的生活阶段",
    ):
        assert marker not in model_text

    assert '"thought": "string"' in prompt.messages[0].content
    assert '"utterance": "string"' in prompt.messages[0].content
    assert '"kind"' not in prompt.messages[0].content
    assert '"character_id"' not in prompt.messages[0].content
    assert snapshot.identity.profile_content in model_text
    assert snapshot.identity.voice_content in model_text
    assert snapshot.identity.relational_dynamics_content in model_text
    assert "你说话像在手机上和一个人聊天" in model_text
    assert "话题可以停在任何地方" in model_text
    assert snapshot.memory_context.resident[0].summary in model_text
    assert snapshot.conversation_continuity.session_digest is not None
    assert snapshot.conversation_continuity.session_digest.content in model_text
    assert snapshot.character_state.current_activity in model_text
    assert "你和对方已经是熟人。" in model_text
    assert turn.player_text in model_text
    assert prompt.tool_definitions[0]["function"]["name"] == "memory_search"


@pytest.mark.asyncio
async def test_character_agent_rejects_an_invocation_for_another_character() -> None:
    catalog = load_identity_catalog(IDENTITY_ROOT)
    turn = load_xiaojin_fixture_turns()[0]
    original_invocation = build_xiaojin_invocation(build_xiaojin_snapshot(catalog, turn))
    invocation = original_invocation.model_copy(
        update={
            "identity": original_invocation.identity.model_copy(
                update={"agent_id": "other.character"}
            )
        }
    )
    agent = CharacterAgent(
        EchoNativeBackend(FakeModelGateway(()), agent_id="xiaojin.character"),
        character_id="xiaojin",
    )

    with pytest.raises(CharacterAgentInvocationError, match="agent id"):
        await agent.run(invocation)


@pytest.mark.asyncio
async def test_xiaojin_character_agent_offline_regression_gate() -> None:
    """Every frozen player input crosses the real Character Agent boundary.

    This is deliberately a structural gate.  The scripted model output only
    proves the Proposal path, prompt projection, forbidden-pattern checks and
    backend interchangeability.  ``ref`` and review notes remain human
    evaluation material rather than becoming an answer oracle.
    """

    catalog = load_identity_catalog(IDENTITY_ROOT)
    turns = load_xiaojin_fixture_turns()
    patterns = load_xiaojin_forbidden_patterns()
    gateway = FakeModelGateway(
        [
            ModelResponse.terminal(
                {
                    "thought": "我先想想该怎样回应。",
                    "utterance": "嗯我在听",
                }
            )
            for _ in turns
        ]
    )
    backend = EchoNativeBackend(gateway, agent_id="xiaojin.character")
    agent = CharacterAgent(backend, character_id="xiaojin")

    for turn in turns:
        snapshot = build_xiaojin_snapshot(catalog, turn)
        result = await agent.run(build_xiaojin_invocation(snapshot))

        assert result.status is AgentRunStatus.COMPLETED
        assert result.stop_reason is AgentStopReason.PROPOSAL_READY
        assert result.output is not None
        proposal = result.output.proposal
        assert result.agent_id == "xiaojin.character"
        assert proposal.payload.character_id == "xiaojin"
        assert proposal.payload.utterance.strip()
        assert_xiaojin_output_clean(proposal.payload.utterance, patterns=patterns)

        request = gateway.requests[-1]
        prompt_text = "\n".join(message.content for message in request.messages)
        assert request.model_profile == "light"
        assert request.output_schema == "character_message.v2"
        assert snapshot.identity.profile_content in prompt_text
        assert snapshot.identity.voice_content in prompt_text
        assert snapshot.identity.relational_dynamics_content in prompt_text
        assert snapshot.character_state.current_activity in prompt_text
        if snapshot.relationship_state.attitude_summary:
            assert snapshot.relationship_state.attitude_summary in prompt_text
        relationship_phrases = {
            "stranger": "你和对方目前还是陌生人。",
            "acquaintance": "你和对方已经是熟人。",
            "friend": "你和对方已经是朋友。",
        }
        assert relationship_phrases[snapshot.relationship_state.relationship_type] in prompt_text
        assert turn.player_text in prompt_text
        assert request.messages[-1].role == "user"
        assert request.messages[-1].content == turn.player_text

    assert len(gateway.requests) == len(turns)


@pytest.mark.real_smoke
@pytest.mark.asyncio
async def test_real_xiaojin_character_agent_smoke() -> None:
    """Opt-in one-turn provider smoke for the configured Character Agent."""

    if os.getenv("ECHO_RUN_REAL_SMOKE") != "1":
        pytest.skip("set ECHO_RUN_REAL_SMOKE=1 to call the configured model provider")

    settings = load_settings()
    agent = build_default_character_agent(settings)
    if not isinstance(agent, CharacterAgent):
        pytest.fail("configured default agent is not a CharacterAgent")
    if isinstance(agent.backend, StubCharacterAgent):
        pytest.fail("real smoke requested but the configured agent resolved to the offline Stub")

    catalog = load_identity_catalog(settings.identity_root)
    turn = next(turn for turn in load_xiaojin_fixture_turns() if turn.scenario_id == "idle_l2")
    snapshot = build_xiaojin_snapshot(catalog, turn)
    route = resolve_agent_route(agent, "conversation.reply")
    result = await agent.run(
        build_xiaojin_invocation(snapshot, model_profile=route.resolved_profile)
    )

    assert result.status is AgentRunStatus.COMPLETED
    assert result.stop_reason is AgentStopReason.PROPOSAL_READY
    assert result.output is not None
    utterance = result.output.proposal.payload.utterance
    assert utterance.strip()
    assert_xiaojin_output_clean(utterance)
    assert result.model_profile == route.resolved_profile

    debug_capture = getattr(agent.backend, "debug_capture", None)
    debug_capture_directory = str(debug_capture.directory) if debug_capture is not None else None
    report_path = Path(__file__).parents[1] / ".runtime" / "smoke" / "xiaojin-character-smoke.json"
    report = {
        "schemaVersion": 1,
        "status": "passed",
        "generatedAtUtc": datetime.now(UTC).isoformat(),
        "agentId": agent.agent_id,
        "characterId": agent.character_id,
        "backend": agent.backend.__class__.__name__,
        "scenarioId": turn.scenario_id,
        "turnIndex": turn.turn_index,
        "scenarioContext": dict(turn.context),
        "route": {
            "taskKind": route.task_kind,
            "requestedProfile": route.requested_profile,
            "resolvedProfile": route.resolved_profile,
            "fallbackReason": route.fallback_reason,
        },
        "identity": {
            "snapshotVersion": snapshot.snapshot_version,
            "promptLayoutVersion": snapshot.prompt_layout_version,
            "contextVersion": snapshot.context_version,
            "baselineVersion": snapshot.identity.contract_version,
            "bundleVersion": snapshot.identity.bundle_version,
            "profileVersion": snapshot.identity.profile_version,
            "relationalDynamicsVersion": snapshot.identity.relational_dynamics_version,
        },
        "input": turn.player_text,
        "output": utterance,
        "checks": {
            "proposalStatus": result.status.value,
            "stopReason": result.stop_reason.value,
            "proposalCount": 1,
            "forbiddenPatterns": "passed",
            "outputNonEmpty": True,
        },
        "usage": result.usage_summary.model_dump(mode="json"),
        "debugCapture": {
            "enabled": debug_capture is not None,
            "directory": debug_capture_directory,
        },
    }
    report_path.parent.mkdir(parents=True, exist_ok=True)
    report_path.write_text(
        json.dumps(report, ensure_ascii=False, indent=2) + "\n",
        encoding="utf-8",
    )
    print(f"Real Character Agent Smoke passed; report: {report_path}")
    if debug_capture_directory is not None:
        print(f"Agent Debug Capture: {debug_capture_directory}")
    print(f"Generated output: {json.dumps(utterance, ensure_ascii=False)}")
