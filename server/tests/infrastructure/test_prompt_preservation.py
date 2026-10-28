from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from support.agents import prepare_system
from support.application import settings_for
from support.historical_messages import historical_message
from support.http import create_group
from support.memory import sealing
from support.reflection import build_reflection
from support.social import build_planning_system, send

from echo_commons.agents.contracts.context import (
    ContextSnapshot,
    ObservedMessage,
    PerspectiveContext,
)
from echo_commons.agents.contracts.output import (
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.agents.harness.prompt import read_prompt_resource
from echo_commons.app.main import create_app
from echo_commons.modules.conversations.domain.message import PlayerMessage
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


@pytest.mark.parametrize("memory_mode", ["simple", "full"])
def test_compact_chat_keeps_unspoken_mentions_and_local_reply_numbers(tmp_path, memory_mode):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client, memory_mode=memory_mode)
        app = client.app.state.application
        first = app.intake.send(
            "community",
            "conversation",
            PlayerMessage(
                "alice",
                "coffee",
                "请帮我准备咖啡。",
                mentions=(
                    ActorRef("character", "first"),
                    ActorRef("character", "second"),
                    ActorRef("player", "bob"),
                ),
            ),
        )
        last = app.intake.send(
            "community",
            "conversation",
            PlayerMessage("alice", "more", "再加一杯牛奶。", reply_to_message_id=first.message_id),
        )
        app.planner.plan()
        with app.database.read() as connection:
            task = connection.execute(
                "SELECT task_id FROM conversation_tasks WHERE character_id='first'"
            ).fetchone()[0]
            snapshot = app.conversation_diagnostics.tasks.snapshot(connection, task)
        snapshot = ContextSnapshot.model_validate_json(snapshot.model_dump_json())
        observed = next(
            item for item in snapshot.perspective.inputs if item.message_id == first.message_id
        )
        assert observed.mention_names == (snapshot.self.name, snapshot.self.name, "bob")
        assert all(item.sender.actor_id == "alice" for item in snapshot.perspective.inputs)
        assert snapshot.perspective.trigger_message_ids == (first.message_id, last.message_id)
        if memory_mode == "simple":
            assert snapshot.self.relationships == ()
        outputs = OutputRegistry()
        outputs.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)
        prompt = project_snapshot(
            snapshot, output_contract=CHARACTER_MESSAGE_CONTRACT, outputs=outputs
        )
        text = "\n".join(message.content for message in prompt.messages)
        assert "本次触发消息" not in text and "原始玩家输入" not in text
        assert first.message_id not in text and last.message_id not in text
        current = [message.content for message in prompt.messages if message.role == "user"]
        assert len(current) == 2
        assert f"提及：{snapshot.self.name}（你）、{snapshot.self.name}、bob" in current[0]
        assert "小槿（1）" not in text and "小槿（2）" not in text
        assert current[0].splitlines()[0].endswith("咖啡。[1]")
        assert current[1].splitlines()[0].endswith("牛奶。[2]")
        assert "回应：alice说的“请帮我准备咖啡。”" in current[1]
        proposal = outputs.parse(CHARACTER_MESSAGE_CONTRACT, {"utterance": "好。", "reply_to": 1})
        assert snapshot.reply_target(proposal.reply_to).message_id == first.message_id
        restored = ContextSnapshot.model_validate_json(snapshot.model_dump_json())
        assert restored.reply_target(2).message_id == last.message_id
        with pytest.raises(ValueError, match="numbered current-conversation message"):
            snapshot.reply_target(3)
        assert app.gateway._clients == {}


def test_own_messages_are_marked_in_current_chat_and_unnumbered_background(tmp_path):
    system = prepare_system(tmp_path)
    invocation = system.executor.prepare(system.task_ids[0], attempt=1).invocation
    snapshot = invocation.context
    own = ActorRef("character", snapshot.scope.character_id)
    private = next(scene for scene in snapshot.scope.conversations if scene.kind == "direct")
    values = dict(
        conversation_id=snapshot.scope.conversation_id,
        occurred_at_utc=snapshot.prepared_at_utc,
        sender_name=snapshot.self.name,
    )
    first = ObservedMessage(
        **values, message_id="own", sequence=1, sender=own, text="我把锅洗好了。"
    )
    second = ObservedMessage(
        **values,
        message_id="other",
        sequence=4,
        sender=ActorRef("character", "another"),
        text="那我准备蔬菜。",
        reply_to_message_id=first.message_id,
        mentions=(own,),
        mention_names=(snapshot.self.name,),
    )
    background = first.model_copy(
        update={"message_id": "private-own", "conversation_id": private.conversation_id}
    )
    snapshot = snapshot.model_copy(
        update={
            "perspective": PerspectiveContext(history=(background, second, first)),
            "scope": snapshot.scope.model_copy(update={"observation_upper_sequence": 4}),
        }
    )
    prompt = project_snapshot(
        snapshot, output_contract=invocation.output_contract, outputs=system.outputs
    )
    own_text = f"{snapshot.self.name}（你）：我把锅洗好了。"
    assert own_text in prompt.messages[1].content
    assert "[1]" not in prompt.messages[1].content
    assert prompt.messages[2].role == "assistant"
    assert own_text + "[1]" in prompt.messages[2].content
    assert f"{snapshot.self.name}：那我准备蔬菜。[2]" in prompt.messages[3].content
    assert f"回应：{snapshot.self.name}（你）说的" in prompt.messages[3].content
    assert f"提及：{snapshot.self.name}（你）" in prompt.messages[3].content
    assert snapshot.reply_target(2).message_id == second.message_id
    with pytest.raises(ValueError):
        snapshot.reply_target(3)
    assert system.gateway._clients == {}


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
        mentions=(ActorRef("character", "first"),),
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
