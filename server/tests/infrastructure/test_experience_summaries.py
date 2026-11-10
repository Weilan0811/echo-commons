import json

from echo_games.aeroplane.rules import AeroplaneRules
from echo_games.public import MovePlaneAction, PlaceStoneAction
from fastapi.testclient import TestClient
from support.activities import activity_game, message
from support.activity_actions import CHARACTER, play_in
from support.application import settings_for
from test_aeroplane_gameplay import request_for

from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.modules.activities.experience_events import describe_event
from echo_commons.modules.reflection.contracts.candidates import ReflectionNodeAction
from echo_commons.modules.reflection.contracts.context import (
    REFLECTION_NODE_CONTRACT,
    GraphContextSnapshot,
)
from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.projection import NodeReferences
from echo_commons.modules.reflection.tasks.prompt import project_node, render_material_groups


def test_action_presentation_preserves_order_sources_and_frozen_originals(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        game = activity_game(client)
        before = message(client, game, "看看这一步。")
        app = client.app.state.application
        with app.database.transaction() as connection:
            play_in(app, connection, game, CHARACTER, PlaceStoneAction(x=7, y=8))
        after = message(client, game, "下次再来。")
        segment = app.memory_sealing.seal("community", "first")
        with app.database.read() as connection:
            graph = app.segment_context.prepare(
                connection, "community", "first", segment.segment_id, utc_now()
            )
            app.segment_context.sources.check_sources(connection, graph)
        node = prepare_node_input(
            graph,
            graph_run_id="presentation",
            node_task_id="summary",
            node_key="segment_summary_plan",
            node_kind=ReflectionNodeKind.SEGMENT_SUMMARY_PLAN,
        )
        labels = NodeReferences.from_input(node)
        rendered = render_material_groups(graph, graph.materials, labels)
        assert rendered.index("黑方落子(7,7)") < rendered.index(before.text)
        assert (
            rendered.index(before.text)
            < rendered.index("白方落子(7,8)")
            < rendered.index(after.text)
        )
        assert "｜活动交流" in rendered
        events = [item for item in graph.materials if item.kind == "game_event"]
        for event in events:
            assert f"[材料{labels.source_label(event.evidence_ref)}]" in rendered
            assert json.loads(event.content)["data"]["type"]
        older = graph.model_dump(mode="json")
        older.pop("summary_task")
        for item in older["materials"]:
            if item["kind"] == "game_event":
                item.pop("description")
                item.pop("sequence")
        legacy = GraphContextSnapshot.model_validate(older)
        assert legacy.model_dump(mode="json") == older
        assert len(rendered) < len(render_material_groups(legacy, legacy.materials, labels))
        with app.database.read() as connection:
            app.segment_context.sources.check_sources(connection, legacy)
        outputs = OutputRegistry()
        outputs.register(REFLECTION_NODE_CONTRACT, ReflectionNodeAction)
        prompt = project_node(node, output_contract=REFLECTION_NODE_CONTRACT, outputs=outputs)
        text = "\n".join(message.content for message in prompt.messages)
        assert "<summary_guidance>" in text and "活动尚未关闭" in text
        assert not app.gateway._clients


def test_aeroplane_description_uses_actual_rule_results_without_inventing_motives():
    state = request_for({"red": {1: 16}, "yellow": {1: 4}}).view.state
    result = AeroplaneRules().apply(state, "red", MovePlaneAction(plane_id=1))
    assert [event.type for event in result.events] == ["plane_walked", "plane_sent_back"]
    descriptions = [describe_event(event) for event in result.events]
    assert descriptions == ["红方1号飞机从进度16移动到17。", "黄方1号飞机因碰撞返回机场。"]
