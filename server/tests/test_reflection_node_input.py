from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
from pydantic import ValidationError
from test_reflection_snapshot import _reflection_context, _source_scope

from echo_server.agents.contracts import (
    CapabilityView,
    GraphContextSnapshot,
    ReflectionSourceMaterial,
)
from echo_server.agents.harness import project_snapshot
from echo_server.domain import (
    EvidenceRef as DomainEvidenceRef,
)
from echo_server.domain import (
    OutputContractRef,
    ReflectionArtifact,
    ReflectionNodeDefinition,
    ReflectionNodeKind,
)
from echo_server.domain.errors import DomainInvariantError
from echo_server.runtime.reflection import NodeInputProjector

BASE_TIME = datetime(2026, 9, 19, 12, tzinfo=UTC)
NODE_CONTRACT = OutputContractRef(kind="reflection_node", version="v1")


def _snapshot() -> GraphContextSnapshot:
    return GraphContextSnapshot.create(
        snapshot_id="snapshot-a",
        account_id="local-player",
        character_id="xiaojin",
        context=_reflection_context(now_utc=BASE_TIME),
        capability_view=CapabilityView(),
        source_scope=_source_scope(),
    )


def _node(
    *,
    node_key: str = "relationship_reflect",
    node_kind: ReflectionNodeKind | str = ReflectionNodeKind.RELATIONSHIP_REFLECT,
    input_contract: str = "segment_summary_context.v1",
) -> ReflectionNodeDefinition:
    return ReflectionNodeDefinition(
        node_key=node_key,
        node_kind=node_kind,
        input_contract=input_contract,
        output_contract=NODE_CONTRACT,
    )


def _artifact() -> ReflectionArtifact:
    return ReflectionArtifact.create(
        artifact_id=uuid4(),
        graph_run_id=uuid4(),
        node_task_id=uuid4(),
        attempt=1,
        node_input_fingerprint="predecessor-input",
        output_contract=NODE_CONTRACT,
        payload={"kind": "segment_summary", "summary": "摘要"},
        evidence_refs=(DomainEvidenceRef(kind="source", ref="message:1", version="message-v1"),),
        created_at_utc=BASE_TIME,
    )


def test_node_input_projects_only_the_declared_node_fields() -> None:
    result = NodeInputProjector().project(
        _snapshot(),
        _node(),
        predecessor_artifacts=(_artifact(),),
    )

    assert result.projection.identity is not None
    assert result.projection.relationship_state is not None
    assert result.projection.character_state is None
    assert result.projection.memory_context is None
    assert result.source_refs == ("message:1",)
    assert result.predecessor_artifacts[0].payload == {"kind": "segment_summary", "summary": "摘要"}
    assert "task_id" not in result.model_dump(mode="json")
    assert "lease" not in result.model_dump(mode="json")


def test_node_input_fingerprint_changes_with_profile_contract_and_artifact() -> None:
    projector = NodeInputProjector()
    snapshot = _snapshot()
    first = projector.project(snapshot, _node(), model_profile="strong")
    second = projector.project(snapshot, _node(), model_profile="light")
    third = projector.project(
        snapshot,
        _node(input_contract="different.v1"),
        model_profile="strong",
    )
    with_artifact = projector.project(snapshot, _node(), predecessor_artifacts=(_artifact(),))

    assert first.node_input_fingerprint != second.node_input_fingerprint
    assert first.node_input_fingerprint != third.node_input_fingerprint
    assert first.node_input_fingerprint != with_artifact.node_input_fingerprint
    assert first.snapshot_ref.snapshot_fingerprint == snapshot.snapshot_fingerprint


def test_resident_memory_is_context_only_and_not_default_evidence() -> None:
    base_context = _reflection_context(now_utc=BASE_TIME)
    context = base_context.model_copy(
        update={
            "materials": (
                *base_context.materials,
                ReflectionSourceMaterial(
                    source_ref="memory:resident-1",
                    source_kind="resident_memory",
                    content="常驻背景记忆",
                ),
            )
        }
    )
    snapshot = GraphContextSnapshot.create(
        snapshot_id="snapshot-a",
        account_id="local-player",
        character_id="xiaojin",
        context=context,
        capability_view=CapabilityView(),
        source_scope=_source_scope(),
    )

    result = NodeInputProjector().project(
        snapshot,
        _node(node_key="segment_summary_plan", node_kind="segment_summary_plan"),
    )

    assert result.source_refs == ("message:1", "memory:resident-1")
    assert tuple(ref.ref for ref in result.evidence_refs) == ("message:1",)
    prompt = project_snapshot(result, output_contract=NODE_CONTRACT)
    prompt_text = "\n".join(message.content for message in prompt.messages)
    assert "memory:resident-1" in prompt_text
    assert "evidence_refs" in prompt_text
    task_text = prompt.messages[-1].content
    assert "本节点可引用的来源：\n- message:1" in task_text
    assert "- memory:resident-1" not in task_text


def test_node_input_rejects_out_of_scope_and_duplicate_evidence() -> None:
    projector = NodeInputProjector()
    with pytest.raises(DomainInvariantError, match="outside"):
        projector.project(
            _snapshot(),
            _node(),
            evidence_refs=(
                # Domain evidence is intentionally used at this Runtime boundary.
                DomainEvidenceRef(kind="source", ref="message:unknown", version="v1"),
            ),
        )

    evidence = DomainEvidenceRef(kind="source", ref="message:1", version="message-v1")
    with pytest.raises(DomainInvariantError, match="unique"):
        projector.project(_snapshot(), _node(), evidence_refs=(evidence, evidence))


def test_node_input_contract_rejects_duplicate_predecessors() -> None:
    artifact = _artifact()
    projector = NodeInputProjector()
    with pytest.raises(ValidationError, match="predecessor Artifacts must be unique"):
        projector.project(
            _snapshot(),
            _node(node_key="segment_aggregate", node_kind="segment_aggregate"),
            predecessor_artifacts=(artifact, artifact),
        )


def test_node_prompt_puts_contract_and_snapshot_before_dynamic_task() -> None:
    node_input = NodeInputProjector().project(
        _snapshot(),
        _node(node_key="segment_summary_plan", node_kind="segment_summary_plan"),
    )

    prompt = project_snapshot(node_input, output_contract=NODE_CONTRACT)
    contents = tuple(message.content for message in prompt.messages)
    assert prompt.messages[0].role == "system"
    assert '"evidence_refs": ["message:<id>", "thought:<id>"]' in contents[0]
    assert "角色以后能回想起来的一段经历" in contents[1]
    assert prompt.messages[-1].role == "user"
    assert "follow_up" in contents[-1]
    assert "message:1" in contents[-1]
    assert "snapshot-a" not in "\n".join(contents)
    assert "节点输入指纹" not in "\n".join(contents)


def test_relationship_node_prompt_declares_exact_action_shape() -> None:
    node_input = NodeInputProjector().project(
        _snapshot(),
        _node(node_key="relationship_reflect", node_kind="relationship_reflect"),
    )

    prompt = project_snapshot(node_input, output_contract=NODE_CONTRACT)
    contract_text = prompt.messages[0].content
    task_text = prompt.messages[-1].content

    assert "当前节点的字段结构" in contract_text
    assert '"dimensions": [' in task_text
    assert '"dimension": "affection"' in task_text
    assert '"direction": "positive"' in task_text
    assert '"level": 1' in task_text
    assert "关系类型、总分、绝对数值、状态期限和数据库 ID 不属于本节点输出" in task_text
    assert "attachment 看更深的信赖" in task_text
    assert "更深的信赖、对对方本人的直接依赖" in task_text


def test_segment_summary_prompt_uses_a_generic_first_person() -> None:
    node_input = NodeInputProjector().project(
        _snapshot(),
        _node(node_key="segment_summary_plan", node_kind="segment_summary_plan"),
    )

    prompt = project_snapshot(node_input, output_contract=NODE_CONTRACT)
    task_text = prompt.messages[-1].content

    assert "以第一人称“我”撰写" in task_text
    assert "提到另一方时使用“对方”" in task_text


def test_page_compose_prompt_declares_multiple_memory_pages() -> None:
    node_input = NodeInputProjector().project(
        _snapshot(),
        _node(
            node_key="page_compose",
            node_kind="page_compose",
            input_contract="memory_organize_context.v1",
        ),
    )

    prompt = project_snapshot(node_input, output_contract=NODE_CONTRACT)
    task_text = prompt.messages[-1].content

    assert '"pages": [' in task_text
    assert "多个互相独立的约定、承诺、事件或事实" in task_text
    assert "同一件事被重复提及时合并为一个 pages 项" in task_text
    assert "conversation_player 只能证明玩家这样说过" in task_text
    assert "常驻记忆只用于理解背景和发现重复" in task_text


def test_continuity_prompt_requires_cumulative_digest_and_exact_coverage() -> None:
    node_input = NodeInputProjector().project(
        _snapshot(),
        _node(
            node_key="continuity_compress",
            node_kind="continuity_compress",
            input_contract="continuity_context.v1",
        ),
    )

    prompt = project_snapshot(node_input, output_contract=NODE_CONTRACT)
    task_text = prompt.messages[-1].content

    assert "可以继续使用的会话连续性摘要" in prompt.messages[1].content
    assert '"kind": "continuity_digest"' in task_text
    assert '"covers_through_sequence": 1' in task_text
    assert "必须返回 continuity_digest" in task_text
    assert "不要返回 no_op" in task_text


def test_graph_extract_prompt_declares_entity_and_edge_contract() -> None:
    node_input = NodeInputProjector().project(
        _snapshot(),
        _node(
            node_key="graph_extract",
            node_kind="graph_extract",
            input_contract="memory_organize_context.v1",
        ),
    )

    prompt = project_snapshot(node_input, output_contract=NODE_CONTRACT)
    task_text = prompt.messages[-1].content

    assert '"entities": [' in task_text
    assert '"edges": [' in task_text
    assert "一条 edge 引用的两个实体都必须出现在本次 entities 中" in task_text
    assert "两个实体同时出现不等于它们存在关系" in task_text
    assert "Runtime 会根据 canonical_name 查找或创建稳定实体" in task_text
    assert "conversation_player 只能证明玩家这样说过" in task_text
