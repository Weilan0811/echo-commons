import asyncio
import json
from functools import partial

import pytest
from echo_games.public import LeaveGameCommand
from fastapi.testclient import TestClient
from support.activities import activity_game, message, prepare
from support.application import settings_for
from support.games import create, operation
from support.http import create_group

from echo_commons.agents.contracts.activity import ActivityUnderstanding, MessageUnderstanding
from echo_commons.app.main import create_app
from echo_commons.modules.activities.gameplay.contracts import GameplayAnalysisError
from echo_commons.modules.activities.tasks.prompt import (
    activity_messages,
    material_size,
    project_activity,
)
from echo_commons.modules.conversations.tasks.memory import ContextBudgetExceeded
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, IdempotencyConflict, NotFoundError


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        yield client


def test_real_turn_freezes_analysis_chat_sources_and_restores_after_restart(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    with TestClient(create_app(settings)) as client:
        game = activity_game(client)
        original = message(client, game, "你下这么厉害，我可要哭了。")
        frozen = prepare(client, game, kind="turn", input_id="turn")
        assert frozen.analysis.legal_action_count == 224
        assert frozen.material.game.state_version == frozen.analysis.state_version
        assert frozen.material.conversation.perspective.trigger_message_ids == (
            original.message_id,
        )
        assert frozen.material.decision_persona.mode == "direct"
        assert frozen.analysis.candidates
        later = message(client, game, "刚才我在开玩笑，来吧。")
        assert prepare(client, game, kind="turn", input_id="turn") == frozen
        assert later.message_id not in frozen.model_dump_json()
        assert material_size(frozen) <= settings.activity.input_max_chars
        assert material_size(frozen, decision=True) <= settings.activity.input_max_chars
        app = client.app.state.application
        with pytest.raises(NotFoundError):
            app.activity_context.restore("community", "second", "turn")
        with pytest.raises(IdempotencyConflict):
            prepare(client, game, kind="reaction", input_id="turn")
        exact = frozen.model_dump_json()
    with TestClient(create_app(settings)) as client:
        restored = client.app.state.application.activity_context.restore(
            "community", "first", "turn"
        )
        assert restored.model_dump_json() == exact
        assert prepare(client, game, kind="turn", input_id="turn").model_dump_json() == exact


def test_consumption_requires_exact_understanding_and_keeps_later_messages_pending(client):
    game = activity_game(client)
    first = message(client, game, "你要是真有本事，试试左上角呀。")
    frozen = prepare(client, game, input_id="reply")
    app = client.app.state.application
    assert app.activity_context.pending_sources("community", "first", game)["message_ids"] == (
        first.message_id,
    )
    later = message(client, game, "等等，我又改主意了。")
    incomplete = ActivityUnderstanding(messages=(), event_ids=())
    with pytest.raises(ValueError, match="exactly"):
        app.activity_context.record_understanding("community", "first", "reply", incomplete)
    # 此处验证接收契约；模型对复杂表达的实际理解另由真实模型测试验证。
    understood = ActivityUnderstanding(
        messages=(
            MessageUnderstanding(message_id=first.message_id, interpretation="带有挑衅的建议"),
        ),
        event_ids=tuple(e.event_id for e in frozen.material.game.events),
        thought="他在激我，我想先看清这个建议的后果。",
    )
    app.activity_context.record_understanding("community", "first", "reply", understood)
    app.activity_context.record_understanding("community", "first", "reply", understood)
    pending = app.activity_context.pending_sources("community", "first", game)
    assert pending["message_ids"] == (later.message_id,)
    next_input = prepare(client, game)
    assert not next_input.material.private_thoughts
    assert "own_private_thoughts" not in activity_messages(next_input)[0].content
    assert next_input.material.conversation.perspective.trigger_message_ids == (later.message_id,)
    with pytest.raises(IdempotencyConflict):
        app.activity_context.record_understanding("community", "first", "reply", incomplete)


def test_reply_and_reaction_exclude_action_permissions_and_reject_empty_sources(client):
    game = activity_game(client)
    message(client, game, "这盘棋要怎么走呀？")
    reply = prepare(client, game)
    reaction = prepare(client, game, kind="reaction")
    for snapshot in (reply, reaction):
        assert not snapshot.material.game.view.opportunities
        assert "analysis" not in snapshot.model_dump()
        assert "opportunity" not in snapshot.model_dump()
        assert "action_analysis" not in activity_messages(snapshot)[0].content
    app = client.app.state.application
    result = ActivityUnderstanding(
        messages=tuple(
            MessageUnderstanding(message_id=i, interpretation="询问行棋")
            for i in reply.material.conversation.perspective.trigger_message_ids
        ),
        event_ids=tuple(e.event_id for e in reply.material.game.events),
    )
    app.activity_context.record_understanding("community", "first", reply.snapshot_id, result)
    with pytest.raises(ConflictError, match="unprocessed"):
        prepare(client, game)
    with pytest.raises(ConflictError, match="visible game events"):
        prepare(client, game, kind="reaction")
    with pytest.raises(ConflictError, match="advanced"):
        app.activity_context.record_understanding(
            "community", "first", reaction.snapshot_id, result
        )


def test_engine_failure_keeps_original_observation_and_completed_stages(client):
    game = activity_game(client)
    first = message(client, game, "你先想想。")
    app = client.app.state.application
    settings = app.rapfi.settings
    app.rapfi.settings = settings.model_copy(update={"timeout_seconds": 0.000001})
    with pytest.raises(GameplayAnalysisError):
        prepare(client, game, kind="turn", input_id="retry")
    with app.database.read() as connection:
        row = connection.execute("SELECT * FROM activity_inputs WHERE input_id='retry'").fetchone()
        assert row["projection_json"] and row["memory_json"]
        assert row["snapshot_json"] is None and row["understanding_json"] is None
    later = message(client, game, "这句话留到下次处理。")
    app.rapfi.settings = settings
    frozen = prepare(client, game, kind="turn", input_id="retry")
    assert frozen.material.conversation.perspective.trigger_message_ids == (first.message_id,)
    assert later.message_id not in frozen.model_dump_json()


def test_necessary_raw_messages_over_budget_fail_without_consuming(client):
    game = activity_game(client)
    original = message(client, game, "重要约定" * 500)
    app = client.app.state.application
    app.activity_context.policy = app.activity_context.policy.model_copy(
        update={"input_max_chars": 200}
    )
    with pytest.raises(ContextBudgetExceeded):
        prepare(client, game, input_id="over-budget")
    assert (
        original.message_id
        in app.activity_context.pending_sources("community", "first", game)["message_ids"]
    )
    with app.database.read() as connection:
        assert (
            connection.execute(
                "SELECT snapshot_json FROM activity_inputs WHERE input_id='over-budget'"
            ).fetchone()[0]
            is None
        )


def test_same_input_concurrent_preparation_reuses_identical_material(client):
    game = activity_game(client)
    message(client, game, "听到啦？")
    app = client.app.state.application

    async def run():
        return await asyncio.gather(
            app.activity_context.prepare_reply("community", "first", game, input_id="parallel"),
            app.activity_context.prepare_reply("community", "first", game, input_id="parallel"),
        )

    first, second = client.portal.call(run)
    assert first == second


def test_rejoined_character_only_reads_new_membership_interval(client):
    create_group(client, memory_mode="simple")
    created, _ = create(client)
    game = created["game_id"]
    operation(
        client,
        game,
        "participants",
        seat_id="white",
        participant={"kind": "character", "character_id": "first"},
    )
    before = message(client, game, "原来参与区间的单独约定")
    frozen = prepare(client, game, input_id="old-interval")
    app = client.app.state.application
    app.game_participation.leave_game(
        ActorRef("player", "alice"),
        LeaveGameCommand(
            game_id=game,
            request_id="remove",
            expected_state_version=2,
            participation_id=frozen.scope.participation_id,
        ),
    )
    gap = message(client, game, "角色不在场时的交流")
    operation(
        client,
        game,
        "participants",
        seat_id="white",
        participant={"kind": "character", "character_id": "first"},
    )
    later = message(client, game, "再次加入后才看到的消息")
    current = prepare(client, game)
    assert current.scope.participation_id != frozen.scope.participation_id
    assert current.scope.membership_id != frozen.scope.membership_id
    assert current.material.conversation.perspective.trigger_message_ids == (later.message_id,)
    content = current.material.conversation.model_dump_json()
    assert before.message_id not in content and gap.message_id not in content
    assert not current.material.working_memory.intents
    with pytest.raises(NotFoundError):
        prepare(client, game, character="second")


def test_live_state_changes_keep_static_persona_and_board(client):
    from echo_commons.modules.characters.domain.state import StateKind

    game = activity_game(client, memory_mode="full")
    message(client, game, "你现在感觉怎么样？")
    first = prepare(client, game)
    app = client.app.state.application
    app.character_state.record(
        "community",
        "first",
        StateKind.MOOD,
        "觉得这局很有意思",
        "manual",
        "test-mood",
        expected_version=1,
    )
    second = prepare(client, game)
    assert second.material.game == first.material.game
    assert second.material.decision_persona == first.material.decision_persona
    assert second.material.conversation.self.mood == "觉得这局很有意思"
    assert first.material.conversation.self.mood != second.material.conversation.self.mood
    assert "觉得这局很有意思" in activity_messages(second, decision=True)[0].content
    assert first == app.activity_context.restore("community", "first", first.snapshot_id)


@pytest.mark.model
def test_real_model_persona_projection_and_message_understanding(client, record_testsuite_property):
    from uuid import uuid4

    from echo_commons.agents.contracts.output import OutputRegistry
    from echo_commons.agents.contracts.refs import OutputContractRef
    from echo_commons.infrastructure.models.protocol import (
        ModelRequest,
        ModelResponseKind,
        PromptMessage,
    )

    game = activity_game(client)
    original = message(client, game, "哟，这么厉害？再赢我我可要哭啦，哈哈。")
    app = client.app.state.application
    persona = app.activity_context.persona
    persona.policy = persona.policy.model_copy(update={"persona_direct_max_chars": 1})
    frozen = prepare(client, game, input_id="model-persona")
    assert frozen.material.decision_persona.mode == "model"
    again = prepare(client, game)
    assert again.material.decision_persona == frozen.material.decision_persona
    with app.database.read() as connection:
        cache = connection.execute("SELECT * FROM activity_persona_projections").fetchall()
        assert len(cache) == 1
        usage = json.loads(cache[0]["response_json"])["usage_summary"]
        assert usage["total_tokens"] > 0 and usage["output_tokens"] > 0
    contract = OutputContractRef(kind="activity_understanding", version="v1")
    outputs = OutputRegistry()
    outputs.register(contract, ActivityUnderstanding)
    prompt = project_activity(
        frozen,
        output_contract=contract,
        outputs=outputs,
        max_content_chars=app.activity_context.policy.input_max_chars,
    )
    assert f"message:{original.message_id}" in prompt.evidence_refs
    with pytest.raises(ContextBudgetExceeded):
        project_activity(
            frozen,
            output_contract=contract,
            outputs=outputs,
            max_content_chars=material_size(frozen),
        )
    request = ModelRequest(
        invocation_id=uuid4(),
        trace_id=uuid4(),
        agent_id="activity-understanding-verification",
        model_profile=persona.model_profile,
        attempt=1,
        step_index=1,
        output_contract=contract,
        messages=(
            *prompt.messages,
            PromptMessage(
                role="user",
                content="只理解本次所有待处理消息，逐条记录含义；event_ids 填入本次全部事件 ID。"
                "不执行动作。只返回符合指定输出结构的 JSON。",
            ),
        ),
        max_output_tokens=3000,
    )
    response = client.portal.call(partial(persona.model_budget.generate, request))
    assert response.kind is ModelResponseKind.TERMINAL
    result = ActivityUnderstanding.model_validate(response.output)
    record_testsuite_property("understanding", result.model_dump_json())
    record_testsuite_property("persona_usage", json.dumps(usage))
    assert result.messages[0].message_id == original.message_id
    assert result.messages[0].interpretation.strip()
    app.activity_context.record_understanding("community", "first", frozen.snapshot_id, result)
    assert not app.activity_context.pending_sources("community", "first", game)["message_ids"]
