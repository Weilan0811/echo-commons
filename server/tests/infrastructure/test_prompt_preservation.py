import ast
from datetime import UTC, datetime
from pathlib import Path

from historical_messages import historical_message
from test_agent_execution import prepare_system
from test_memory_sealing import sealing
from test_reflection_context import build_reflection
from test_social_planning import build_planning_system, send

from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.harness.prompt import read_prompt_resource
from echo_commons.modules.conversations.tasks.prompt import (
    project_snapshot,
    render_conversation_guidance,
)
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.reflection.contracts.candidates import ReflectionNodeAction
from echo_commons.modules.reflection.contracts.context import REFLECTION_NODE_CONTRACT
from echo_commons.modules.reflection.domain.graph import (
    ReflectionGraphKind,
    ReflectionNodeKind,
    reflection_graph_definition,
)
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.projection import project_node_input
from echo_commons.modules.reflection.tasks.prompt import project_node, render_node_task
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
            render_node_task(node, ("message:actual",), 3)
            for kind in ReflectionGraphKind
            if kind is not ReflectionGraphKind.DIARY_COMPOSE
            for node in reflection_graph_definition(kind).nodes
            if node.prompt_resource
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
    original_tree = ast.parse(baseline.read_text(encoding="utf-8"))
    resources = Path(__file__).resolve().parents[2] / "src/echo_commons/resources/prompts"
    current_prose = "\n".join(path.read_text(encoding="utf-8") for path in resources.rglob("*.md"))
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
        "字段结构遵循本次对话约定，并保持为一个 JSON 对象。",
        "对象只能包含 thought 和 utterance 两个字段；"
        "utterance 必须是非空字符串，thought 可以为空。",
        "dimensions 是 JSON 数组；每一项包含 dimension、direction、level。",
        "dimension 使用 affection、trust、attachment，每个维度最多出现一次。",
        "不要输出 Markdown、解释、日志或 JSON 之外的文字，也不要谈论自己正在执行什么要求。",
    }
    example = next(value for value in prose(original_tree) if '"dimensions"' in value)
    changes.add(example)
    changes.add(next(value for value in prose(original_tree) if value.startswith("你说话像在手机")))
    changes.add(
        next(value for value in prose(original_tree) if value.startswith("角色资料说明你是谁"))
    )
    changes.add(next(value for value in prose(original_tree) if value.startswith("本批次没有可用")))
    revised_paragraphs = (
        "你现在做的是角色自己的回看。",
        "凡是输出摘要、记忆、日记、状态或关系视图等正文，",
        "evidence_refs 只填写输入中显示、",
        "没有可以可靠归纳的内容时返回 kind=no_op",
        "最后的节点说明会给出当前节点的字段结构。",
        "字段名和层级请与下面的格式示意保持一致。",
        "不要输出 Markdown、解释、日志、额外文字，",
        "正文保持角色第一人称，字段按照当前节点动作的结构填写；",
        "写法可以接近：",
        "summary 覆盖本次消息与 thought 能支持的内容，",
    )
    for prefix in revised_paragraphs:
        changes.add(next(value for value in prose(original_tree) if value.startswith(prefix)))
    assert len(prose(original_tree)) > 70
    assert {value for value in prose(original_tree) if value not in current_prose} == changes
    assert read_prompt_resource("reflection/materials/dialogue.md") in baseline.read_text(
        encoding="utf-8"
    ).replace('"\n        "', "")


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
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    system.planner.plan()
    with system.database.read() as connection:
        second_task = connection.execute(
            "SELECT task_id FROM conversation_tasks "
            "WHERE status='pending' AND character_id='second'"
        ).fetchone()[0]
        snapshots["second"] = system.tasks.snapshot(connection, second_task)
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
    assert "你负责把当前来源段整理成角色以后能回想起来的一段经历。" in text
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
