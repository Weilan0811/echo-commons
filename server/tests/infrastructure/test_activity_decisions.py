import pytest
from fastapi.testclient import TestClient
from support.activities import activity_game, message, prepare
from support.activity_actions import task_row
from support.application import settings_for

from echo_commons.agents.contracts.activity import (
    ActivityDecision,
    ActivitySelection,
    ActivityTurnProposal,
    ActivityUnderstanding,
    MessageUnderstanding,
)
from echo_commons.agents.contracts.output import (
    CharacterMessageProposal,
    CheckedCharacterExpression,
)
from echo_commons.app.main import create_app
from echo_commons.modules.activities.decisions import build_decision, new_messages, selection_goal
from echo_commons.modules.activities.tasks.prompt import decision_material, decision_questions


def test_local_and_full_decisions_bind_the_same_real_turn_and_preserve_actual_content(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        game = activity_game(client)
        sent = message(client, game, "哈哈，这回可别放过我！")
        app = client.app.state.application
        (identity,) = app.activity_coordinator.scan()
        row = task_row(app, identity)
        snapshot = prepare(client, game, kind="turn", input_id=row["input_id"])
        questions = decision_questions(snapshot)
        question = questions["expression"]
        assert "express" not in question.criteria
        assert {"reply_messages", "comment_action", "react_events", "silent", "understand"} == set(
            question.criteria
        )
        assert selection_goal(snapshot, question, "silent") is None
        assert selection_goal(snapshot, question, "understand") is None
        goal = selection_goal(snapshot, question, "reply_messages")
        assert goal.evidence_refs == (f"message:{sent.message_id}",)
        action_goal = selection_goal(snapshot, question, "comment_action")
        assert action_goal.evidence_refs == (f"activity_input:{snapshot.snapshot_id}",)
        action = snapshot.analysis.candidates[0].action
        selection = ActivitySelection[type(action)](
            action=action,
            retained_intent_ids=(),
            expression_needed=True,
            expression_goal=goal,
        )
        app.activity_execution.review.proposal(row, selection, snapshot)
        local = build_decision(row, {"mode": "decision"}, snapshot, selection)
        assert local.thought is None and local.speech.kind == "compose"
        assert local.speech.goal == goal
        assert local.subject.action == action.model_dump(mode="json")
        assert local.input_id == snapshot.snapshot_id and local.decision_id == identity
        assert ActivityDecision.model_validate_json(local.model_dump_json()) == local
        silent = build_decision(
            row,
            {"mode": "decision"},
            snapshot,
            selection.model_copy(update={"expression_needed": False, "expression_goal": None}),
        )
        assert silent.speech.kind == "silent" and silent.thought is None
        body = CheckedCharacterExpression(
            claims=(),
            message=CharacterMessageProposal(utterance="那我就认真想想这一步。"),
        )
        proposal = ActivityTurnProposal[type(action)](
            action=action,
            intents=(),
            expression=body,
            understanding=ActivityUnderstanding(
                messages=(
                    MessageUnderstanding(
                        message_id=sent.message_id, interpretation="带着玩笑的挑战"
                    ),
                ),
                event_ids=tuple(e.event_id for e in snapshot.material.game.events),
                thought="我想回应他的挑战。",
            ),
        )
        app.activity_execution.review.proposal(row, proposal, snapshot)
        full = build_decision(row, {"mode": "ordinary"}, snapshot, proposal)
        assert full.subject == local.subject and full.speech.expression == body
        assert full.thought == proposal.understanding.thought
        with pytest.raises(ValueError, match="frozen activity input"):
            app.activity_execution.review.proposal(
                row,
                selection.model_copy(
                    update={
                        "expression_goal": goal.model_copy(
                            update={"evidence_refs": ("message:unknown",)}
                        ),
                    }
                ),
                snapshot,
            )
        assert not app.gateway._clients


def test_intent_question_reads_new_sources_and_stops_revisiting_old_material(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        game = activity_game(client)
        first = message(client, game, "我们慢慢来吧。")
        snapshot = prepare(client, game, kind="turn")
        assert [m.message_id for m in new_messages(snapshot)] == [first.message_id]
        assert "intent_update" in decision_questions(snapshot)
        app = client.app.state.application
        with app.database.transaction() as connection:
            app.activity_context.record_selection_in(
                connection, "community", "first", snapshot.snapshot_id
            )
        later = prepare(client, game, kind="turn")
        assert not new_messages(later) and not later.material.game.events
        assert "intent_update" not in decision_questions(later)
        assert first.message_id in later.model_dump_json()
        own = message(client, game, "还可以换个玩法。")
        latest = prepare(client, game, kind="turn")
        assert decision_material(latest)["新增来源"]["message_ids"] == [own.message_id]
        assert "intent_update" in decision_questions(latest)
