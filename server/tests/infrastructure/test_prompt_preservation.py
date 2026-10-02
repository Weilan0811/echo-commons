import ast
from pathlib import Path

from test_agent_execution import prepare_system
from test_memory_sealing import sealing
from test_reflection_context import build_reflection

from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.harness.prompt import (
    render_conversation_guidance,
    render_node_responsibility,
    render_node_task,
)
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.modules.reflection.contracts.candidates import ReflectionNodeAction
from echo_commons.modules.reflection.contracts.context import REFLECTION_NODE_CONTRACT
from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.projection import project_node_input
from echo_commons.modules.reflection.tasks.prompt import project_node


def test_fixed_prompt_paragraphs_match_preserved_baseline():
    baseline = Path(__file__).resolve().parents[3] / "docs/prompt-audit/original-prompt.py.txt"
    tree = ast.parse(baseline.read_text(encoding="utf-8"))
    fixed = []
    for node in tree.body:
        if isinstance(node, ast.Assign) and any(
            isinstance(target, ast.Name)
            and target.id in {"_NODE_RESPONSIBILITIES", "_MEMORY_ORGANIZE_SOURCE_GUIDANCE"}
            for target in node.targets
        ):
            value = ast.literal_eval(node.value)
            fixed.extend(value.values() if isinstance(value, dict) else value)
        if isinstance(node, ast.FunctionDef) and node.name == "render_conversation_guidance":
            fixed.extend(
                item.value
                for item in ast.walk(node)
                if isinstance(item, ast.Constant)
                and isinstance(item.value, str)
                and len(item.value) > 30
                and "\n" not in item.value
            )
    rendered = (
        render_conversation_guidance()
        + "\n"
        + "\n".join(
            render_node_responsibility(kind) + "\n" + render_node_task(kind, ("message:actual",), 3)
            for kind in (
                "segment_summary_plan",
                "relationship_reflect",
                "state_reflect",
                "continuity_compress",
                "page_compose",
                "graph_extract",
            )
        )
    )
    assert len(fixed) == 15
    assert all(value in rendered for value in fixed)


def test_real_conversation_and_graph_projection_contains_complete_prose(tmp_path):
    system = prepare_system(tmp_path)
    invocation = system.executor.prepare(system.task_ids[0], attempt=1).invocation
    prompt = project_snapshot(
        invocation.context, output_contract=invocation.output_contract, outputs=system.outputs
    )
    assert render_conversation_guidance() in prompt.messages[0].content
    tags = (
        "response_contract",
        "conversation_guidance",
        "agent_contract",
        "character_profile",
        "character_relational_dynamics",
        "character_voice",
        "current_state",
        "relationship_state",
        "continuity_memory",
        "conversation_history",
    )
    positions = [prompt.messages[0].content.index("<" + tag + ">") for tag in tags]
    assert positions == sorted(positions)
    segment = sealing(system).seal("community", invocation.scope.character_id, "conversation")
    _, coordinator = build_reflection(system)
    run = coordinator.start_segment("community", invocation.scope.character_id, segment.segment_id)
    with system.database.read() as connection:
        snapshot = RunRepository().snapshot(
            connection, "community", invocation.scope.character_id, str(run.graph_run_id)
        )
    node = prepare_node_input(
        snapshot,
        graph_run_id=str(run.graph_run_id),
        node_task_id="projection",
        node_key="segment_summary_plan",
        node_kind=ReflectionNodeKind.SEGMENT_SUMMARY_PLAN,
    )
    outputs = OutputRegistry()
    outputs.register(REFLECTION_NODE_CONTRACT, ReflectionNodeAction)
    prompt = project_node(node, output_contract=REFLECTION_NODE_CONTRACT, outputs=outputs)
    text = "\n".join(message.content for message in prompt.messages)
    assert render_node_responsibility("segment_summary_plan") in text
    assert "summary 是角色留给自己的一小段回忆。" in text
    assert "<character_voice>" not in text
    assert "artifact:" not in prompt.messages[-1].content
    for kind in (ReflectionNodeKind.RELATIONSHIP_REFLECT, ReflectionNodeKind.STATE_REFLECT):
        projected_node = prepare_node_input(
            snapshot,
            graph_run_id=str(run.graph_run_id),
            node_task_id=kind.value,
            node_key=kind.value,
            node_kind=kind,
        )
        projection = project_node_input(projected_node)
        assert projection.memory == ""
        assert (projection.state != "") == (kind is ReflectionNodeKind.STATE_REFLECT)
        assert (projection.relationships != "") == (kind is ReflectionNodeKind.RELATIONSHIP_REFLECT)
        assert all(material.kind in {"message", "thought"} for material in projection.materials)
        prompt = project_node(
            projected_node, output_contract=REFLECTION_NODE_CONTRACT, outputs=outputs
        )
        text = "\n".join(message.content for message in prompt.messages)
        assert "你一直记得的一些事情：" not in text
        assert ("你此刻的状态：" in text) == (kind is ReflectionNodeKind.STATE_REFLECT)
        assert ("你和对方现在的相处：" in text) == (kind is ReflectionNodeKind.RELATIONSHIP_REFLECT)
