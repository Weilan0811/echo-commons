import ast
from datetime import UTC, datetime
from pathlib import Path

from historical_messages import historical_message
from test_agent_execution import prepare_system
from test_memory_sealing import sealing
from test_reflection_context import build_reflection
from test_social_planning import build_planning_system, send

from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.harness.prompt import (
    render_conversation_guidance,
    render_node_responsibility,
    render_node_task,
    render_reflection_source_introduction,
)
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.reflection.contracts.candidates import ReflectionNodeAction
from echo_commons.modules.reflection.contracts.context import REFLECTION_NODE_CONTRACT
from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.projection import project_node_input
from echo_commons.modules.reflection.tasks.prompt import project_node
from echo_commons.shared.actors import ActorRef


def test_fixed_prompt_paragraphs_match_preserved_baseline():
    baseline = (
        Path(__file__).resolve().parents[3]
        / "docs/temp_doc/rebuild-01/prompt-audit/original-prompt.py.txt"
    )
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
    retained = [value for value in fixed if not value.startswith("你说话像在手机")]
    assert len(retained) == 14
    assert all(value in rendered for value in retained)


def test_all_fixed_output_and_node_prose_matches_baseline_except_declared_fields():
    baseline = (
        Path(__file__).resolve().parents[3]
        / "docs/temp_doc/rebuild-01/prompt-audit/original-prompt.py.txt"
    )
    current = Path(__file__).resolve().parents[2] / "src/echo_commons/agents/harness/prompt.py"
    original_tree = ast.parse(baseline.read_text(encoding="utf-8"))
    current_tree = ast.parse(current.read_text(encoding="utf-8"))
    names = {
        "render_output_contract",
        "render_conversation_guidance",
        "render_expression_guidance",
        "render_node_task",
    }

    def prose(tree):
        strings = set()
        for function in tree.body:
            if isinstance(function, ast.FunctionDef) and function.name in names:
                docstring = (
                    function.body[0].value.value
                    if isinstance(function.body[0], ast.Expr)
                    and isinstance(function.body[0].value, ast.Constant)
                    else None
                )
                strings.update(
                    node.value
                    for node in ast.walk(function)
                    if isinstance(node, ast.Constant)
                    and isinstance(node.value, str)
                    and len(node.value) > 15
                    and node.value != docstring
                    and any("\u4e00" <= character <= "\u9fff" for character in node.value)
                )
        return strings

    changes = {
        "对象只能包含 thought 和 utterance 两个字段；"
        "utterance 必须是非空字符串，thought 可以为空。",
        "dimensions 是 JSON 数组；每一项包含 dimension、direction、level。",
        "dimension 使用 affection、trust、attachment，每个维度最多出现一次。",
    }
    example = next(value for value in prose(original_tree) if '"dimensions"' in value)
    changes.add(example)
    changes.add(next(value for value in prose(original_tree) if value.startswith("你说话像在手机")))
    assert len(prose(original_tree)) > 70
    assert prose(original_tree) - prose(current_tree) == changes
    assert render_reflection_source_introduction() in baseline.read_text(encoding="utf-8").replace(
        '"\n        "', ""
    )


def test_conversation_reads_own_uncompressed_segment_summaries(tmp_path):
    system = build_planning_system(tmp_path)
    private = historical_message(
        system, "我会带草莓417。", recipients=(ActorRef("character", "first"),)
    )
    segment = sealing(system).seal("community", "first", "conversation")
    summary = "我记得对方约定带草莓417。"
    with system.database.transaction() as connection:
        MemoryIngestion(SegmentRepository(), CoverageRepository()).ingest(
            connection, "community", "first", segment.segment_id, summary, datetime.now(UTC)
        )
    system.planner.plan()
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    system.conversations.join("community", "conversation", ActorRef("character", "first"))
    send(
        system,
        "大家现在开始准备晚餐。",
        mentions=(ActorRef("character", "first"), ActorRef("character", "second")),
    )
    system.planner.plan()
    with system.database.read() as connection:
        tasks = connection.execute(
            "SELECT task_id,character_id FROM conversation_tasks "
            "WHERE status = 'pending' AND character_id IN ('first','second')"
        ).fetchall()
        snapshots = {
            task["character_id"]: system.tasks.snapshot(connection, task["task_id"])
            for task in tasks
        }
    first = snapshots["first"]
    assert len(first.memory.segment_summaries) == 1
    material = first.memory.segment_summaries[0]
    assert material.segment_id == segment.segment_id
    assert material.first_sequence == material.last_sequence == private.sequence
    assert summary in first.model_dump_json()
    assert snapshots["second"].memory.segment_summaries == ()
    assert "草莓417" not in snapshots["second"].model_dump_json()
    assert any(
        source.source_id == segment.segment_id and source.version == "1"
        for source in first.source_versions
    )


def test_real_conversation_and_graph_projection_contains_complete_prose(tmp_path):
    system = prepare_system(tmp_path)
    invocation = system.executor.prepare(system.task_ids[0], attempt=1).invocation
    prompt = project_snapshot(
        invocation.context, output_contract=invocation.output_contract, outputs=system.outputs
    )
    assert render_conversation_guidance() in prompt.messages[0].content
    tags = (
        "response_contract",
        "agent_contract",
        "character_profile",
        "character_relational_dynamics",
        "character_voice",
        "conversation_guidance",
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
