"""Regression contracts for the frozen Xiaojin Identity conversation fixture."""

from __future__ import annotations

from datetime import UTC, datetime
from pathlib import Path
from uuid import uuid4

import yaml

from echo_server.agents.contracts import (
    PROMPT_LAYOUT_VERSION,
    AgentMessage,
    CharacterStateSnapshot,
    ContextRequest,
    ContextSnapshotV2,
    IdentityContext,
    OutputContractRef,
    RelationshipStateSnapshot,
)
from echo_server.agents.harness import CHARACTER_MESSAGE_OUTPUT_SCHEMA, project_snapshot
from echo_server.services.identity import IdentityCatalog, load_identity_catalog

SERVER_ROOT = Path(__file__).parents[1]
IDENTITY_ROOT = SERVER_ROOT / "config" / "identity"
GOLDEN_PATH = SERVER_ROOT / "tests" / "fixtures" / "identity" / "xiaojin" / "golden.yaml"

EXPECTED_GOLDEN_VERSION = "0.3.0-draft"
EXPECTED_IDENTITY_VERSION = "0.5.0-draft"
EXPECTED_BASELINE_VERSION = "0.6.1-draft"

EXPECTED_SCENARIO_CONTEXTS = {
    "idle_l1": {
        "relationship_type": "stranger",
        "world_phase": "solo",
        "relationship_evidence": "none",
        "physical_condition": "身体状态和平时差不多",
        "mood": "平常",
        "current_activity": "正在画画",
    },
    "idle_l2": {
        "relationship_type": "acquaintance",
        "world_phase": "solo",
        "relationship_evidence": "repeated_proactive_sharing",
        "physical_condition": "身体状态和平时差不多",
        "mood": "平常",
        "current_activity": "正在赶一份画稿",
    },
    "low_mood_l2": {
        "relationship_type": "acquaintance",
        "world_phase": "solo",
        "relationship_evidence": "repeated_proactive_sharing",
        "physical_condition": "久坐后肩膀有些僵",
        "mood": "有点烦",
        "current_activity": "画稿卡在一处细节上",
    },
    "care_l2": {
        "relationship_type": "acquaintance",
        "world_phase": "solo",
        "relationship_evidence": "mutual_sharing",
        "physical_condition": "身体状态和平时差不多",
        "mood": "平常",
        "current_activity": "刚忙完一幅画",
    },
}

EXPECTED_PLAYER_INPUTS = {
    "idle_l1": (
        "哈哈哈我刚刷到一个视频,一只猫卡在花盆里出不来了,笑死",
        "你最近都在忙什么呀",
        "就你一个人住吗?不会无聊吗",
    ),
    "idle_l2": (
        "哈哈哈我刚刷到一个视频,一只猫卡在花盆里出不来了,笑死",
        "哈哈我也想养一只了",
        "那你画过它吗",
    ),
    "low_mood_l2": (
        "你今天好像有点安静,怎么了?",
        "真的没事?",
        "那早点休息,画稿明天再搞",
    ),
    "care_l2": (
        "跟你说个事,我今天被领导当众批了一顿,挺难受的。",
        "嗯……就是个方案改来改去,最后还是用第一版。",
        "没事了,跟你说完好多了。",
    ),
}


def _load_golden() -> dict[str, object]:
    value = yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8"))
    assert isinstance(value, dict)
    return value


def _mapping(value: object) -> dict[str, object]:
    assert isinstance(value, dict)
    return value


def _scenario(golden: dict[str, object], scenario_id: str) -> dict[str, object]:
    scenarios = golden["scenarios"]
    assert isinstance(scenarios, list)
    for value in scenarios:
        scenario = _mapping(value)
        if scenario["id"] == scenario_id:
            return scenario
    raise AssertionError(f"missing scenario: {scenario_id}")


def _snapshot_for(
    catalog: IdentityCatalog,
    *,
    player_text: str,
) -> ContextSnapshotV2:
    message = AgentMessage(
        message_id=uuid4(),
        sender_type="player",
        sender_id="local-player",
        text=player_text,
        server_timestamp_utc=datetime(2026, 9, 7, 12, 0, tzinfo=UTC),
    )
    baseline = catalog.default_baseline
    identity = catalog.character("xiaojin")
    return ContextSnapshotV2(
        conversation_id="xiaojin",
        character_id="xiaojin",
        context_version="fixture-context-v1",
        now_utc=message.server_timestamp_utc,
        request=ContextRequest(
            conversation_id="xiaojin",
            character_id="xiaojin",
            trigger_message=message,
            input_messages=(message,),
        ),
        identity=IdentityContext(
            contract_resource_id=baseline.resource_id,
            contract_content=baseline.content,
            contract_version=baseline.content_version,
            character_id=identity.resource_id,
            bundle_version=identity.content_version,
            profile_resource_id=identity.profile.resource_id,
            profile_content=identity.profile.content,
            profile_version=identity.profile.content_version,
            voice_resource_id=identity.voice.resource_id if identity.voice is not None else None,
            voice_content=identity.voice.content if identity.voice is not None else "",
            voice_version=identity.voice.content_version if identity.voice is not None else None,
            relational_dynamics_resource_id=(
                identity.relational_dynamics.resource_id
                if identity.relational_dynamics is not None
                else None
            ),
            relational_dynamics_content=(
                identity.relational_dynamics.content
                if identity.relational_dynamics is not None
                else ""
            ),
            relational_dynamics_version=(
                identity.relational_dynamics.content_version
                if identity.relational_dynamics is not None
                else None
            ),
        ),
        character_state=CharacterStateSnapshot(
            character_id="xiaojin",
            availability_status="",
            availability_updated_at_utc=message.server_timestamp_utc,
        ),
        relationship_state=RelationshipStateSnapshot(subject_id="local-player"),
        prompt_layout_version=PROMPT_LAYOUT_VERSION,
    )


def test_xiaojin_golden_versions_match_the_runtime_identity_bundle() -> None:
    golden = _load_golden()
    catalog = load_identity_catalog(IDENTITY_ROOT)

    assert golden["schema_version"] == 1
    assert golden["golden_version"] == EXPECTED_GOLDEN_VERSION
    assert golden["character_id"] == "xiaojin"
    assert golden["identity_version"] == EXPECTED_IDENTITY_VERSION
    assert golden["baseline_version"] == EXPECTED_BASELINE_VERSION
    assert golden["prompt_layout_version"] == PROMPT_LAYOUT_VERSION
    assert catalog.character("xiaojin").content_version == golden["identity_version"]
    assert catalog.default_baseline.content_version == golden["baseline_version"]


def test_xiaojin_player_inputs_and_contexts_are_frozen() -> None:
    golden = _load_golden()
    scenarios = golden["scenarios"]
    assert isinstance(scenarios, list)
    assert tuple(_mapping(scenario)["id"] for scenario in scenarios) == tuple(
        EXPECTED_PLAYER_INPUTS
    )

    for scenario_id, expected_inputs in EXPECTED_PLAYER_INPUTS.items():
        scenario = _scenario(golden, scenario_id)
        context = _mapping(scenario["context"])
        assert context == EXPECTED_SCENARIO_CONTEXTS[scenario_id]
        turns = scenario["turns"]
        assert isinstance(turns, list)
        assert tuple(_mapping(turn)["player"] for turn in turns) == expected_inputs
        assert all("ref" in _mapping(turn) for turn in turns)
        assert all("review_expectations" in _mapping(turn) for turn in turns)


def test_xiaojin_fixture_uses_identity_prompt_layout_without_reference_replies() -> None:
    golden = _load_golden()
    catalog = load_identity_catalog(IDENTITY_ROOT)
    turns = _scenario(golden, "idle_l1")["turns"]
    assert isinstance(turns, list)
    first_turn = _mapping(turns[0])
    player_text = first_turn["player"]
    assert isinstance(player_text, str)

    prompt = project_snapshot(
        _snapshot_for(catalog, player_text=player_text),
        output_contract=OutputContractRef(kind="character_message", version="v2"),
    )

    assert prompt.output_schema == CHARACTER_MESSAGE_OUTPUT_SCHEMA
    assert prompt.baseline_version == EXPECTED_BASELINE_VERSION
    assert prompt.identity_version == EXPECTED_IDENTITY_VERSION
    assert [message.role for message in prompt.messages] == ["system", "user"]
    prompt_text = prompt.messages[0].content
    assert catalog.default_baseline.content in prompt_text
    assert catalog.character("xiaojin").profile.content in prompt_text
    assert catalog.character("xiaojin").relational_dynamics.content in prompt_text
    assert "<response_contract>" in prompt_text
    assert "对象只能包含 thought 和 utterance" in prompt_text
    assert "你始终以角色本人存在和回应" not in prompt_text
    assert "<conversation_guidance>" in prompt_text
    assert "<agent_contract>" in prompt_text
    assert "<character_profile>" in prompt_text
    assert "<character_relational_dynamics>" in prompt_text
    assert "<character_voice>" in prompt_text
    assert "从角色此刻的生活、记忆、感受和正在发生的事出发回应。" in prompt_text
    assert "你谈到过去时，先回想自己能确认的记忆和已有对话" in prompt_text
    assert "<relationship_state>" in prompt_text
    assert "你和对方目前还是陌生人。" in prompt_text
    model_messages = prompt.messages[1:]
    assert tuple((message.role, message.content) for message in model_messages) == (
        ("user", player_text),
    )
    references = first_turn["ref"]
    assert isinstance(references, list)
    assert all(isinstance(reference, str) for reference in references)
    model_input = "\n".join(message.content for message in model_messages)
    assert all(reference not in model_input for reference in references)
