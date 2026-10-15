from datetime import UTC, datetime

from support.agents import prepare_system
from support.historical_messages import historical_message
from support.memory import sealing
from support.reflection import build_reflection
from support.social import build_planning_system, send

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
    ReflectionNodeKind,
)
from echo_commons.modules.reflection.repositories.runs import RunRepository
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.projection import project_node_input
from echo_commons.modules.reflection.tasks.prompt import project_node
from echo_commons.shared.actors import ActorRef


def test_conversation_reads_own_uncompressed_segment_summaries(tmp_path):
    system = build_planning_system(tmp_path)
    private = historical_message(
        system, "我会带草莓417。", recipients=(ActorRef("character", "first"),)
    )
    segment = sealing(system).seal("community", "first")
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
    assert material.started_at_utc == material.ended_at_utc == private.created_at_utc
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
        "conversation_history",
    )
    positions = [prompt.messages[0].content.index("<" + tag + ">") for tag in tags]
    assert positions == sorted(positions)
    segment = sealing(system).seal("community", invocation.scope.character_id)
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
    assert read_prompt_resource("reflection/nodes/segment_summary_plan.md").strip() in text
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
