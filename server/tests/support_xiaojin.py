"""Shared builders for the offline and opt-in Xiaojin Agent gates.

The fixture loader intentionally exposes only player inputs and scenario
context.  Reference replies and human review notes stay in ``golden.yaml``
for manual evaluation and never become an automated answer oracle.
"""

from __future__ import annotations

import re
from collections.abc import Mapping
from dataclasses import dataclass
from datetime import UTC, datetime, timedelta
from pathlib import Path
from re import Pattern
from uuid import NAMESPACE_URL, uuid5

import yaml

from echo_commons.agents.contracts import (
    AgentInvocation,
    AgentMessage,
    CapabilityDefinition,
    CapabilityView,
    CharacterStateSnapshot,
    ContextInputRef,
    ContextRequest,
    ContextSnapshotV2,
    ConversationContinuity,
    ConversationScope,
    Correlation,
    ExecutionPolicy,
    IdentityContext,
    InvocationIdentity,
    MemoryContext,
    MemoryItem,
    OutputContractRef,
    RelationshipStateSnapshot,
    SessionDigest,
    SituationView,
    SnapshotSourceVersion,
)
from echo_commons.services.identity import IdentityCatalog

SERVER_ROOT = Path(__file__).parents[0]
IDENTITY_ROOT = SERVER_ROOT.parent / "config" / "identity"
GOLDEN_PATH = SERVER_ROOT / "fixtures" / "identity" / "xiaojin" / "golden.yaml"
BASE_TIME = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


@dataclass(frozen=True, slots=True)
class XiaojinFixtureTurn:
    """The model-input portion of one frozen regression turn."""

    scenario_id: str
    turn_index: int
    player_text: str
    context: Mapping[str, str]


def load_xiaojin_fixture_turns() -> tuple[XiaojinFixtureTurn, ...]:
    """Load all fixed player inputs without reading reference replies."""

    golden = _mapping(yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8")))
    scenarios = golden.get("scenarios")
    if not isinstance(scenarios, list):
        raise AssertionError("xiaojin golden scenarios must be a list")
    turns: list[XiaojinFixtureTurn] = []
    for raw_scenario in scenarios:
        scenario = _mapping(raw_scenario)
        scenario_id = _string(scenario.get("id"), "scenario id")
        context = {
            key: _string(value, f"{scenario_id}.{key}")
            for key, value in _mapping(scenario.get("context")).items()
        }
        raw_turns = scenario.get("turns")
        if not isinstance(raw_turns, list):
            raise AssertionError(f"{scenario_id}.turns must be a list")
        for turn_index, raw_turn in enumerate(raw_turns, start=1):
            turn = _mapping(raw_turn)
            turns.append(
                XiaojinFixtureTurn(
                    scenario_id=scenario_id,
                    turn_index=turn_index,
                    player_text=_string(turn.get("player"), "player input"),
                    context=context,
                )
            )
    return tuple(turns)


def load_xiaojin_forbidden_patterns() -> tuple[Pattern[str], ...]:
    """Compile the automatic output rules from the frozen fixture."""

    golden = _mapping(yaml.safe_load(GOLDEN_PATH.read_text(encoding="utf-8")))
    raw_rules = golden.get("common_forbid")
    if not isinstance(raw_rules, list):
        raise AssertionError("xiaojin golden common_forbid must be a list")
    return tuple(
        re.compile(_string(_mapping(rule).get("pattern"), "forbidden pattern"))
        for rule in raw_rules
    )


def assert_xiaojin_output_clean(
    utterance: str,
    *,
    patterns: tuple[Pattern[str], ...] | None = None,
) -> None:
    """Apply only automatic fixture rules, without asserting a reference reply."""

    for pattern in patterns or load_xiaojin_forbidden_patterns():
        if pattern.search(utterance) is not None:
            raise AssertionError(f"output matched forbidden regression rule: {pattern.pattern!r}")


def build_xiaojin_snapshot(
    catalog: IdentityCatalog,
    turn: XiaojinFixtureTurn,
) -> ContextSnapshotV2:
    """Build a complete synthetic V2 snapshot for one frozen player input."""

    now_utc = BASE_TIME + timedelta(minutes=turn.turn_index)
    message_id = uuid5(
        NAMESPACE_URL,
        f"https://echo.test/xiaojin-regression/{turn.scenario_id}/{turn.turn_index}",
    )
    message = AgentMessage(
        message_id=message_id,
        sender_type="player",
        sender_id="local-player",
        text=turn.player_text,
        server_timestamp_utc=now_utc,
    )
    baseline = catalog.default_baseline
    identity = catalog.character("xiaojin")
    capabilities = tuple(
        CapabilityDefinition(
            name=capability.name,
            description=capability.description,
            parameters=dict(capability.parameters),
            action_kind=capability.action_kind,
        )
        for capability in sorted(identity.capabilities, key=lambda item: item.name)
    )

    relationship_type = turn.context.get("relationship_type", "stranger")
    evidence = turn.context.get("relationship_evidence", "none")
    evidence_summary = {
        "none": "她和对方还在轻松地试探彼此",
        "repeated_proactive_sharing": "她已经习惯和对方分享一些小事",
        "mutual_sharing": "她和对方都愿意说一点自己的事",
    }.get(evidence, "她还在观察这段相处")
    is_low_mood = turn.context.get("mood") == "有点烦"
    physical_condition = turn.context.get("physical_condition", "身体状态和平时差不多")
    current_activity = turn.context.get("current_activity", "正在画画")

    context_version = f"xiaojin-regression-{turn.scenario_id}-turn-{turn.turn_index}"
    return ContextSnapshotV2(
        conversation_id="xiaojin",
        character_id="xiaojin",
        context_version=context_version,
        now_utc=now_utc,
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
            availability_version=1,
            availability_status="available",
            physical_condition=physical_condition,
            mood="有点烦" if is_low_mood else "平常",
            current_activity=current_activity,
            availability_updated_at_utc=now_utc,
        ),
        relationship_state=RelationshipStateSnapshot(
            subject_id="local-player",
            state_version=1,
            relationship_type=relationship_type,
            affection=30.0 if relationship_type != "stranger" else None,
            trust=25.0 if relationship_type != "stranger" else None,
            attachment=5.0 if relationship_type != "stranger" else None,
            attitude_summary=(evidence_summary if relationship_type != "stranger" else ""),
            updated_at_utc=now_utc,
        ),
        memory_context=MemoryContext(
            resident=(
                MemoryItem(
                    memory_id="fixture-resident-preference-1",
                    summary="她画累时偶尔会去附近的便利店买点甜的",
                    memory_kind="preference",
                    source="fixture",
                ),
            ),
            resident_version="xiaojin-regression-memory-v1",
        ),
        conversation_continuity=ConversationContinuity(
            session_digest=SessionDigest(
                digest_id=f"{context_version}-digest",
                content="这是同一段连续对话中的一个轻量回归片段",
                covers_through_sequence=turn.turn_index,
                content_version="xiaojin-regression-digest-v1",
                created_at_utc=now_utc,
            ),
            recent_tail=(),
            raw_tail_limit=20,
        ),
        situation=SituationView(
            world_phase=turn.context.get("world_phase", "solo"),
            stage_summary="独奏期",
            uncertainty_note="她只能从眼前的聊天和自己记得的事情理解这段情境",
            world_time_utc=now_utc,
        ),
        capability_view=CapabilityView(available=capabilities),
        source_versions=(
            SnapshotSourceVersion(source="fixture.character_state", version="v1"),
            SnapshotSourceVersion(source="fixture.relationship_state", version="v1"),
            SnapshotSourceVersion(source="fixture.memory", version="v1"),
            SnapshotSourceVersion(source="fixture.session_digest", version="v1"),
        ),
    )


def build_xiaojin_invocation(
    snapshot: ContextSnapshotV2,
    *,
    model_profile: str = "light",
) -> AgentInvocation:
    """Create a bounded one-step invocation for a regression or smoke gate."""

    seed = f"https://echo.test/xiaojin-invocation/{snapshot.context_version}"
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
        execution_policy=ExecutionPolicy(
            model_profile=model_profile,
            harness_version="harness-v4",
            max_model_steps=1,
            max_model_requests=1,
            max_tool_calls=0,
        ),
        correlation=Correlation(
            task_id=uuid5(NAMESPACE_URL, f"{seed}/task"),
            trace_id=uuid5(NAMESPACE_URL, f"{seed}/trace"),
        ),
    )


def _mapping(value: object) -> dict[str, object]:
    if not isinstance(value, dict):
        raise AssertionError("fixture value must be a mapping")
    return value


def _string(value: object, name: str) -> str:
    if not isinstance(value, str) or not value.strip():
        raise AssertionError(f"{name} must be a non-empty string")
    return value


__all__ = [
    "BASE_TIME",
    "GOLDEN_PATH",
    "IDENTITY_ROOT",
    "SERVER_ROOT",
    "XiaojinFixtureTurn",
    "assert_xiaojin_output_clean",
    "build_xiaojin_invocation",
    "build_xiaojin_snapshot",
    "load_xiaojin_fixture_turns",
    "load_xiaojin_forbidden_patterns",
]
