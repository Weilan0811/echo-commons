import sqlite3
from datetime import datetime

from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.continuation import ContinuationPolicy
from echo_commons.modules.social.contracts import ParticipationResult, TaskCancellationPort
from echo_commons.modules.social.events import turns_changed
from echo_commons.modules.social.repository import SocialRepository


class SocialLifecycle:
    def __init__(
        self, social: SocialRepository, completion: TurnCompletion, tasks: TaskCancellationPort
    ) -> None:
        self.social, self.completion, self.tasks = social, completion, tasks

    def message_received(self, connection: sqlite3.Connection, message: Message) -> None:
        chain = self.social.active_chain(connection, message.conversation_id)
        if (
            chain
            and (reason := ContinuationPolicy.stop_reason(chain))
            and not self.social.running(connection, message.conversation_id)
        ):
            self.completion.close_round(
                connection, chain, reason, message.created_at_utc, self.tasks
            )
            return
        if chain:
            self.social.attach_message(connection, chain.chain_id, message.message_id)

    def cancel_conversation(
        self, connection, conversation_id: str, reason: str, at: datetime
    ) -> None:
        for row in connection.execute(
            "SELECT social_turn_id FROM social_turns WHERE conversation_id=? "
            "AND status IN ('pending','running')",
            (conversation_id,),
        ).fetchall():
            self.tasks.cancel_turn(connection, row[0], reason, at)
            self.social.cancel_turn(connection, row[0], reason, at)
            turns_changed(connection, row[0])
        chain = self.social.active_chain(connection, conversation_id)
        if chain:
            self.social.stop_chain(connection, chain.chain_id, reason, at, cancelled=True)
            for row in connection.execute(
                "SELECT social_turn_id FROM social_turns WHERE chain_id=?", (chain.chain_id,)
            ):
                turns_changed(connection, row[0])

    def task_finished(self, connection, result: ParticipationResult, at: datetime) -> None:
        changed = self.social.complete_participation(
            connection, result.turn_id, result.character_id, result.status, result.outcome, at
        )
        if not changed:
            return
        turn = self.social.by_id(connection, result.turn_id)
        if turn.chain_id:
            if result.membership_id and result.considered_through_sequence is not None:
                self.social.observe(
                    connection,
                    turn.chain_id,
                    result.membership_id,
                    result.considered_through_sequence,
                )
            if result.message:
                self.social.message_created(connection, turn.chain_id)
                self.social.attach_message(connection, turn.chain_id, result.message.message_id)
        self.completion.update(connection, result.turn_id, at)
        if turn.chain_id:
            chain = self.social.chain(connection, turn.chain_id)
            if chain.status == "active" and (reason := ContinuationPolicy.stop_reason(chain)):
                self.completion.close_round(connection, chain, reason, at, self.tasks)
        turns_changed(connection, result.turn_id)

    def player_left(self, connection, membership_id, at):
        # 私聊只对原玩家安排回应；群聊的其他成员继续交流。
        for row in connection.execute(
            "SELECT DISTINCT t.social_turn_id FROM social_turns t "
            "JOIN conversations c USING(conversation_id) "
            "JOIN social_turn_batches b USING(social_turn_id) "
            "JOIN input_batch_messages bm USING(input_batch_id) JOIN messages m USING(message_id) "
            "WHERE c.kind='direct' AND m.sender_membership_id=? AND t.status='running'",
            (membership_id,),
        ).fetchall():
            self.tasks.cancel_turn(connection, row[0], "member_left", at)
            self.social.cancel_turn(connection, row[0], "member_left", at)
            turns_changed(connection, row[0])
