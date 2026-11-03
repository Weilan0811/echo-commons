from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.modules.activities.domain.task import task_view
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


class ActivityReview:
    def __init__(self, observations, conversations, communities):
        self.observations, self.conversations, self.communities = (
            observations,
            conversations,
            communities,
        )

    def source_code(self, connection, row, *, require_action=None):
        try:
            context = self.observations.participation.participant_context(
                connection,
                row["community_id"],
                ActorRef("character", row["character_id"]),
                row["game_id"],
                row["participation_id"],
            )
            conversation = self.conversations.get(
                connection, row["community_id"], row["conversation_id"]
            )
            member = self.conversations.current(
                connection, row["conversation_id"], ActorRef("character", row["character_id"])
            )
        except NotFoundError:
            return "participation_ended"
        if conversation.status != "active" or member.membership_id != row["membership_id"]:
            return "conversation_archived"
        expression = row["purpose"] == "expression"
        reply = not (row["purpose"] == "turn" if require_action is None else require_action)
        if (
            reply
            and not expression
            and not connection.execute(
                "SELECT 1 FROM activity_task_sources WHERE task_id=? "
                "AND status IN ('attached','frozen')",
                (row["task_id"],),
            ).fetchone()
        ):
            return "source_replaced"
        if context.game.status == "cancelled":
            return "participation_ended"
        if not reply and (
            context.game.status != "running" or context.game.state_version != row["state_version"]
        ):
            return "opportunity_replaced"
        if self.communities.get(connection, row["community_id"]).status != "active":
            return "community_paused"
        reason = self.observations.eligibility.reason(
            connection, row["community_id"], member.actor, context.game
        )
        if reason:
            return "character_unavailable"
        view = self.observations.games.read_view(connection, context.access) if not reply else None
        if not reply and not any(
            o.opportunity_id == row["opportunity_id"] for o in view.opportunities
        ):
            return "opportunity_replaced"
        return None

    def can_requeue_reply(self, connection, row):
        # 暂停或暂时不可用只限制执行，仍然有效的交流来源应当保留。
        return self.source_code(connection, row, require_action=False) in (
            None,
            "community_paused",
            "character_unavailable",
        )

    def proposal(self, row, proposal, snapshot):
        if not snapshot.material.expression_allowed and getattr(proposal, "expression", None):
            raise ExecutionError(
                "expression_not_arranged", FailureCategory.REVIEW, RecoveryAction.RETRY_TASK
            )
        if row["purpose"] == "turn":
            view = task_view(row)
            opportunity = next(
                o for o in view.opportunities if o.opportunity_id == row["opportunity_id"]
            )
        if row["purpose"] == "turn" and proposal.action not in opportunity.legal_actions:
            raise ExecutionError(
                "activity_action_illegal", FailureCategory.REVIEW, RecoveryAction.RETRY_TASK
            )
        if hasattr(proposal, "understanding"):
            actual = proposal.understanding
            expected = snapshot.material.conversation.perspective.trigger_message_ids
            ids = [m.message_id for m in actual.messages]
            events = [e.event_id for e in snapshot.material.game.events]
            if (
                set(ids) != set(expected)
                or len(ids) != len(set(ids))
                or set(actual.event_ids) != set(events)
                or len(actual.event_ids) != len(events)
            ):
                raise ExecutionError(
                    "activity_understanding_incomplete",
                    FailureCategory.REVIEW,
                    RecoveryAction.RETRY_TASK,
                )
            messages = {m.message_id for m in snapshot.material.conversation.current_messages}
            if snapshot.material.game.status != "running" and proposal.intents:
                raise ExecutionError(
                    "activity_intent_outside_match",
                    FailureCategory.REVIEW,
                    RecoveryAction.RETRY_TASK,
                )
            if any(
                not i.content.strip() or not set(i.message_ids) <= messages
                for i in proposal.intents
            ):
                raise ExecutionError(
                    "activity_intent_source_invalid",
                    FailureCategory.REVIEW,
                    RecoveryAction.RETRY_TASK,
                )
            if proposal.expression and proposal.expression.message.reply_to:
                try:
                    snapshot.material.conversation.reply_target(
                        proposal.expression.message.reply_to
                    )
                except ValueError as error:
                    raise ExecutionError(
                        "reply_target_unknown", FailureCategory.REVIEW, RecoveryAction.RETRY_TASK
                    ) from error
