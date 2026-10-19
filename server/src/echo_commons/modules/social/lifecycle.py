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
        self,
        social: SocialRepository,
        completion: TurnCompletion,
        tasks: TaskCancellationPort,
    ) -> None:
        self.social, self.completion, self.tasks = social, completion, tasks

    def player_input(self, connection: sqlite3.Connection, message: Message) -> None:
        self.cancel_conversation(
            connection,
            message.conversation_id,
            "player_input",
            message.created_at_utc,
        )

    def cancel_conversation(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        reason: str,
        at: datetime,
    ) -> None:
        initiations = connection.execute(
            "SELECT social_turn_id FROM social_turns WHERE conversation_id=? "
            "AND chain_id IS NULL AND initiation_id IS NOT NULL "
            "AND status IN ('pending','running')",
            (conversation_id,),
        ).fetchall()
        for row in initiations:
            self.tasks.cancel_turn(connection, row[0], reason, at)
            self.social.cancel_turn(connection, row[0], reason, at)
            turns_changed(connection, row[0])
        rows = connection.execute(
            "SELECT chain_id FROM social_chains WHERE conversation_id=? AND status='active'",
            (conversation_id,),
        ).fetchall()
        for row in rows:
            for turn in connection.execute(
                "SELECT social_turn_id FROM social_turns WHERE chain_id=? AND status='running'",
                (row["chain_id"],),
            ).fetchall():
                self.tasks.cancel_turn(connection, turn[0], reason, at)
                self.social.cancel_turn(connection, turn[0], reason, at)
                turns_changed(connection, turn[0])
            self.social.stop_chain(connection, row["chain_id"], reason, at, cancelled=True)
            for turn in connection.execute(
                "SELECT social_turn_id FROM social_turns WHERE chain_id=?", (row["chain_id"],)
            ).fetchall():
                turns_changed(connection, turn[0])

    def task_finished(
        self,
        connection: sqlite3.Connection,
        result: ParticipationResult,
        at: datetime,
    ) -> None:
        changed = self.social.complete_participation(
            connection,
            result.turn_id,
            result.character_id,
            result.status,
            result.outcome,
            at,
        )
        if not changed:
            return
        turn = self.social.by_id(connection, result.turn_id)
        turns_changed(connection, result.turn_id)
        if turn.chain_id and result.message is not None:
            self.social.message_created(connection, turn.chain_id)
            chain = self.social.chain(connection, turn.chain_id)
            reason = ContinuationPolicy.stop_reason(chain)
            if result.batch_id is None:
                raise ValueError("Character message requires its input batch")
            self.social.trigger(connection, turn.chain_id, result.turn_id, result.batch_id, at)
            if reason:
                self.social.stop_chain(connection, turn.chain_id, reason, at)
        self.completion.update(connection, result.turn_id, at)

    def player_left(self, connection, membership_id, at):
        roots = connection.execute(
            "SELECT DISTINCT t.social_turn_id,t.chain_id,t.conversation_id FROM social_turns t "
            "JOIN social_turn_batches b ON b.social_turn_id=t.social_turn_id "
            "JOIN input_batch_messages bm USING(input_batch_id) JOIN messages m USING(message_id) "
            "WHERE m.sender_membership_id=? AND m.sender_kind='player' AND t.status='running'",
            (membership_id,),
        ).fetchall()
        for root in roots:
            if root["chain_id"]:
                self.cancel_conversation(connection, root["conversation_id"], "member_left", at)
            else:
                self.tasks.cancel_turn(connection, root["social_turn_id"], "member_left", at)
                self.social.cancel_turn(connection, root["social_turn_id"], "member_left", at)
                turns_changed(connection, root["social_turn_id"])
        # 已完成根轮次的后续回应仍依赖原玩家。
        chains = connection.execute(
            "SELECT DISTINCT c.conversation_id FROM social_chains c "
            "JOIN social_turn_batches b ON b.social_turn_id=c.root_turn_id "
            "JOIN input_batch_messages bm USING(input_batch_id) JOIN messages m USING(message_id) "
            "WHERE c.status='active' AND m.sender_membership_id=? AND m.sender_kind='player'",
            (membership_id,),
        ).fetchall()
        for chain in chains:
            self.cancel_conversation(connection, chain[0], "member_left", at)
