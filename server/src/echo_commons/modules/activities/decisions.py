from echo_commons.agents.contracts.activity import (
    ActivityDecision,
    ActivityScope,
    ComposeDecision,
    DecisionReply,
    DecisionTurn,
    ExpressionGoal,
    IntentProposal,
    ReadyDecision,
    SilentDecision,
)
from echo_commons.agents.contracts.input import SourceVersion
from echo_commons.modules.activities.domain.task import task_view


def handoff_reasons(response):
    return tuple(key for key, answer in response.answers.items() if answer.choice == "understand")


def new_messages(snapshot):
    material = snapshot.material
    pending = set(material.conversation.perspective.trigger_message_ids)
    return tuple(
        m
        for m in material.conversation.current_messages
        if m.message_id in pending or m.sequence > material.game.after_message_sequence
    )


def selection_goal(snapshot, question, choice):
    if choice in ("silent", "understand"):
        return None
    material = snapshot.material
    if choice in ("participate", "reply_messages"):
        refs = tuple(f"message:{i}" for i in material.conversation.perspective.trigger_message_ids)
        if not refs:
            refs = tuple(
                f"game_event:{i}"
                for i in (*material.reaction_event_ids, *(e.event_id for e in material.game.events))
            )
    elif choice == "react_events":
        refs = tuple(
            f"game_event:{i}"
            for i in (*material.reaction_event_ids, *(e.event_id for e in material.game.events))
        )
    else:
        refs = (f"activity_input:{snapshot.snapshot_id}",)
    return ExpressionGoal(
        purpose=question.criteria[choice],
        evidence_refs=tuple(dict.fromkeys(refs)) or (f"activity_input:{snapshot.snapshot_id}",),
    )


def build_decision(row, artifact, snapshot=None, proposal=None):
    mode = artifact["mode"]
    automatic = mode == "automatic"
    reply = row["purpose"] == "reply"
    if automatic:
        view = task_view(row)
        scope = ActivityScope(
            community_id=row["community_id"],
            character_id=row["character_id"],
            game_id=row["game_id"],
            participation_id=row["participation_id"],
            seat_id=view.viewer_seat_id,
            conversation_id=row["conversation_id"],
            membership_id=row["membership_id"],
        )
        action = next(
            o for o in view.opportunities if o.opportunity_id == row["opportunity_id"]
        ).legal_actions[0]
        intents, thought, speech = None, None, SilentDecision()
        sources = (
            SourceVersion(kind="game", source_id=scope.game_id, version=str(view.state_version)),
        )
    else:
        scope = snapshot.scope
        action = None if reply else proposal.action
        if mode == "decision":
            retained = set(proposal.retained_intent_ids)
            intents = tuple(
                IntentProposal(content=i.content, message_ids=i.message_ids)
                for i in snapshot.material.working_memory.intents
                if i.intent_id in retained
            )
            thought = None
            if proposal.expression_needed:
                if proposal.expression_goal is None:
                    raise ValueError("A new local expression decision requires an explicit goal")
                speech = ComposeDecision(goal=proposal.expression_goal)
            else:
                speech = SilentDecision()
        else:
            intents = proposal.intents
            thought = proposal.understanding.thought.strip() or None
            speech = (
                ReadyDecision(
                    expression=proposal.expression,
                    comments_on_action=getattr(proposal, "comments_on_action", False),
                )
                if proposal.expression
                else SilentDecision()
            )
        sources = snapshot.source_versions
    response = artifact.get("decision_response")
    reasons = (
        tuple(
            key for key, answer in response["answers"].items() if answer["choice"] == "understand"
        )
        if response
        else ()
    )
    return ActivityDecision(
        decision_id=row["task_id"],
        input_id=None if automatic else snapshot.snapshot_id,
        mode=mode,
        scope=scope,
        state_version=view.state_version if automatic else snapshot.material.game.state_version,
        working_memory_version=None if automatic else snapshot.material.working_memory.version,
        subject=DecisionReply()
        if reply
        else DecisionTurn(
            opportunity_id=row["opportunity_id"], action=action.model_dump(mode="json")
        ),
        speech=speech,
        intents=intents,
        thought=thought,
        source_versions=sources,
        handoff_reasons=reasons,
    )
