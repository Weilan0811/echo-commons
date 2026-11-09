import json

import pytest
from echo_games.public import PlaceStoneAction
from fastapi.testclient import TestClient
from support.activities import activity_game, message, prepare
from support.activity_actions import ALICE, play_in
from support.application import settings_for
from support.migrations import load_history

from echo_commons.agents.contracts.activity import (
    ActivityExpressionProposal,
    ActivitySelection,
    TurnExpressionStage,
)
from echo_commons.agents.contracts.output import CheckedCharacterExpression
from echo_commons.app.composition import assemble
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.activities.decisions import build_decision, selection_goal
from echo_commons.modules.activities.tasks.prompt import (
    activity_messages,
    decision_questions,
    project_activity,
)


def saved_turn(tmp_path):
    database = load_history(31, tmp_path / "history.sqlite3")
    initialize(database)
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={
            "database_path": str(database.path),
            "retry_backoff_seconds": 0,
        }
    )
    app = assemble(settings)
    with database.transaction() as connection:
        for turn in connection.execute(
            "SELECT social_turn_id FROM social_turns WHERE status='running'"
        ).fetchall():
            app.planner.tasks.cancel_turn(connection, turn[0], "cancelled", utc_now())
            app.planner.social.cancel_turn(connection, turn[0], "cancelled", utc_now())
        result = dict(connection.execute("SELECT * FROM activity_results").fetchone())
        app.activity_lifecycle.reconcile_in(connection, utc_now())
    return app, settings, result


def test_turn_body_input_preserves_the_selected_action_and_original_reply_numbers(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        game = activity_game(client)
        sent = message(client, game, "你打算怎么回应这一手？")
        original = prepare(client, game, kind="turn")
        app = client.app.state.application
        goal = selection_goal(
            original, decision_questions(original)["expression"], "comment_action"
        )
        action = original.analysis.candidates[0].action
        decision = build_decision(
            {
                "task_id": "turn",
                "purpose": "turn",
                "opportunity_id": original.opportunity.opportunity_id,
            },
            {"mode": "decision"},
            original,
            ActivitySelection[type(action)](
                action=action, retained_intent_ids=(), expression_needed=True, expression_goal=goal
            ),
        )
        value = app.activity_execution.turn_expressions.snapshot(
            original, decision.model_dump(mode="json"), "turn", generate=True
        )
        with app.database.transaction() as connection:
            value = app.activity_expressions._complete_input_in(connection, value)
        assert value.phase == "before_action" and value.receipt is None
        assert not value.material.game.view.opportunities
        projected = project_activity(
            value,
            output_contract=value.action_space.output_contracts[0],
            outputs=app.activity_execution.outputs,
        )
        assert not any("activity_result:" in ref for ref in projected.evidence_refs)
        assert value.origin.decision["subject"]["action"] == action.model_dump(mode="json")
        assert value.origin.state_version == original.material.game.state_version
        assert (
            value.material.conversation.current_messages
            == original.material.conversation.current_messages
        )
        number = next(
            n
            for n, m in enumerate(value.material.conversation.current_messages, 1)
            if m.message_id == sent.message_id
        )
        assert value.material.conversation.reply_target(number).message_id == sent.message_id
        assert "<expression_phase>" in activity_messages(value)[0].content
        stage = TurnExpressionStage(input=value)
        assert TurnExpressionStage.model_validate_json(stage.model_dump_json()) == stage
        assert not app.gateway._clients


@pytest.mark.asyncio
async def test_saved_action_survives_publication_failure_and_restart_without_regeneration(tmp_path):
    app, settings, result = saved_turn(tmp_path)
    lease = app.activity_expressions._claim_turn(result["result_id"])
    snapshot = app.activity_expressions.prepare(lease)
    proposal = ActivityExpressionProposal(
        expression=CheckedCharacterExpression.model_validate_json(result["expression_json"])
    )
    app.activity_expressions.save_stage(lease, "prepared_json", proposal.model_dump_json())
    blocker = app.database.connect()
    try:
        blocker.execute("BEGIN IMMEDIATE")
        with pytest.raises(StorageError) as failure:
            app.activity_expressions.publish(lease, snapshot, proposal)
        assert failure.value.retryable
    finally:
        blocker.rollback()
        blocker.close()
    await app.activity_expressions.queue.apply_recovery(
        lease, utc_now(), app.activity_expressions.queue.recovery.classify(failure.value)
    )
    with app.database.transaction() as connection:
        row = app.activity_expressions.tasks.get(connection, result["result_id"])
        assert row["status"] == "retry_wait" and row["prepared_json"] is not None
        assert row["receipt_json"] == result["receipt_json"]
        assert (
            app.activity_commit.results.for_task(connection, result["task_id"])[
                "publication_status"
            ]
            == "pending"
        )
    restarted = assemble(settings)
    await restarted.activity_expressions.complete_turn(result["result_id"])
    await restarted.activity_expressions.complete_turn(result["result_id"])
    with restarted.database.read() as connection:
        saved = restarted.activity_commit.results.for_task(connection, result["task_id"])
        assert saved["publication_status"] == "published"
        assert saved["receipt_json"] == result["receipt_json"]
        messages = connection.execute(
            "SELECT text FROM messages WHERE activity_result_id=?", (result["result_id"],)
        ).fetchall()
        assert [m[0] for m in messages] == [
            json.loads(result["expression_json"])["message"]["utterance"]
        ]
        source = connection.execute(
            "SELECT status,social_turn_id FROM activity_task_sources WHERE task_id=?",
            (result["task_id"],),
        ).fetchone()
        assert source["status"] == "published"
        assert (
            restarted.planner.social.decisions(connection, source["social_turn_id"])[0].outcome
            == "message"
        )
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    assert not app.gateway._clients and not restarted.gateway._clients


@pytest.mark.asyncio
async def test_player_progress_closes_the_original_action_expression_window(tmp_path):
    app, _, result = saved_turn(tmp_path)
    receipt = json.loads(result["receipt_json"])
    with app.database.transaction() as connection:
        play_in(app, connection, receipt["game_id"], ALICE, PlaceStoneAction(x=0, y=0))
    await app.activity_expressions.complete_turn(result["result_id"])
    with app.database.read() as connection:
        saved = app.activity_commit.results.for_task(connection, result["task_id"])
        assert saved["publication_status"] == "cancelled"
        assert saved["receipt_json"] == result["receipt_json"]
        expression = app.activity_expressions.tasks.get(connection, result["result_id"])
        assert expression["last_error_code"] == "expression_window_closed"
        assert not connection.execute(
            "SELECT 1 FROM messages WHERE activity_result_id=?", (result["result_id"],)
        ).fetchone()
    assert not app.gateway._clients
