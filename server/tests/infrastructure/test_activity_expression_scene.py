import asyncio
from contextlib import suppress

from fastapi.testclient import TestClient
from support.activities import activity_game, message, prepare
from support.application import settings_for
from support.historical_messages import historical_message

from echo_commons.agents.contracts.activity import ActivityExpressionInput, ActivityReplySelection
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.modules.activities.tasks.prompt import activity_messages, project_activity
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.shared.actors import ActorRef


def capture(app, original):
    with app.database.transaction() as connection:
        value = app.activity_context.expression_input_in(
            connection,
            original,
            utc_now(),
            expression_id="scene",
            decision=ActivityReplySelection(
                retained_intent_ids=(), expression_needed=True
            ).model_dump(),
        )
        return app.activity_expressions._complete_input_in(connection, value)


def test_expression_scene_uses_new_chat_and_preserves_frozen_reply_numbers(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        game = activity_game(client)
        app = client.app.state.application
        before = message(client, game, "上一回合真惊险。")
        original = prepare(client, game, input_id="origin")
        newer = message(client, game, "先别说上一回合了，你觉得现在该怎么办？")
        nearby = app.intake.send(
            "community", "conversation", PlayerMessage("alice", "nearby", "晚点一起吃饭。")
        )
        hidden = historical_message(
            app, "这是只告诉另一个角色的私事。", recipients=(ActorRef("character", "second"),)
        )
        pending = app.activity_context.pending_sources("community", "first", game)
        fresh = capture(app, original)
        assert fresh.material.conversation.memory.context_prepared
        assert fresh.prepared_at_utc > original.prepared_at_utc
        assert fresh.origin.message_upper_sequence < fresh.material.game.through_message_sequence
        assert fresh.origin.message_ids == (before.message_id,)
        projected = project_activity(
            fresh,
            output_contract=fresh.action_space.output_contracts[0],
            outputs=app.activity_execution.outputs,
        )
        assert f"activity_input:{original.snapshot_id}" in projected.evidence_refs
        common = fresh.material.conversation
        ids = {m.message_id for m in common.current_messages}
        assert {before.message_id, newer.message_id} <= ids
        assert nearby.message_id in {m.message_id for m in common.perspective.history}
        assert hidden.message_id not in fresh.model_dump_json()
        assert common.perspective.trigger_message_ids == ()
        assert app.activity_context.pending_sources("community", "first", game) == pending
        number = next(
            n for n, m in enumerate(common.current_messages, 1) if m.message_id == newer.message_id
        )
        exact = fresh.model_dump_json()
        later = message(client, game, "这句话等下次再说。")
        restored = ActivityExpressionInput.model_validate_json(exact)
        assert restored.material.conversation.reply_target(number).message_id == newer.message_id
        assert later.message_id not in restored.model_dump_json()
        assert newer.message_id not in original.model_dump_json()
        text = "\n".join(m.content for m in activity_messages(restored))
        assert "<original_decision>" in text and newer.text in text
        assert not app.gateway._clients


def test_model_reservation_captures_scene_after_wait_and_releases_on_cancel(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(update={"model_concurrency": 1})
    with TestClient(create_app(settings)) as client:
        game = activity_game(client)
        message(client, game, "等一下。")
        app = client.app.state.application
        original = prepare(client, game)
        budget = app.activity_expressions.model_budget

        async def run():
            started, captured = asyncio.Event(), asyncio.Event()
            values = []

            async def prepare_scene():
                started.set()
                async with budget.reservation(priority=1):
                    async with budget.slot():
                        values.append(capture(app, original))
                        captured.set()
                    await asyncio.Event().wait()

            async with budget.slot():
                task = asyncio.create_task(prepare_scene())
                await started.wait()
                assert not captured.is_set()
                newer = message(client, game, "等名额时又有了新的话题。")
            try:
                await asyncio.wait_for(captured.wait(), timeout=5)
                assert budget._active == 1
            finally:
                task.cancel()
                with suppress(asyncio.CancelledError):
                    await task
            assert budget._active == 0
            async with budget.slot():
                assert budget._active == 1
            return values[0], newer

        fresh, newer = client.portal.call(run)
        assert newer.message_id in {
            m.message_id for m in fresh.material.conversation.current_messages
        }
        assert not app.gateway._clients
