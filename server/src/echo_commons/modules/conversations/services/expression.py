from uuid import uuid4
from zoneinfo import ZoneInfo

from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.conversations.services.events import message_created
from echo_commons.shared.actors import ActorRef


class ExpressionService:
    def __init__(self, review, conversations, messages, batches, indexer, thoughts, communities):
        self.review, self.conversations, self.messages = review, conversations, messages
        self.batches, self.indexer, self.thoughts, self.communities = (
            batches,
            indexer,
            thoughts,
            communities,
        )

    def check(self, connection, snapshot, proposal):
        return self.review.expression(connection, snapshot, proposal)

    def save_in(
        self,
        connection,
        snapshot,
        proposal,
        *,
        audience,
        visibility,
        trace_id,
        now,
        result_id=None,
        activity_result_id=None,
        turn_id=None,
    ):
        if not connection.in_transaction:
            raise RuntimeError("Expression persistence requires a caller-owned transaction")
        if (result_id is None) == (activity_result_id is None):
            raise ValueError("Expression requires exactly one real result source")
        column, identity = (
            ("result_id", result_id) if result_id else ("activity_result_id", activity_result_id)
        )
        existing = connection.execute(
            f"SELECT message_id FROM messages WHERE {column}=?", (identity,)
        ).fetchone()
        if existing:
            return self.messages.get(connection, snapshot.scope.conversation_id, existing[0]), None
        scope = snapshot.scope
        message = Message(
            str(uuid4()),
            scope.community_id,
            scope.conversation_id,
            self.conversations.allocate_sequence(connection, scope.conversation_id, now),
            ActorRef("character", scope.character_id),
            scope.membership_id,
            proposal.utterance,
            visibility,
            audience,
            (),
            snapshot.reply_target(proposal.reply_to).message_id
            if proposal.reply_to is not None
            else None,
            None,
            turn_id or scope.social_turn_id,
            result_id,
            trace_id,
            now,
            activity_result_id,
        )
        self.messages.add(connection, message)
        message_created(connection, message)
        batch_id = self.batches.collect(connection, message, quiet_seconds=0)
        self.indexer.message(connection, message)
        # 活动内心已随活动决定保存，正文生成不会再次复制原内心。
        if result_id and proposal.thought.strip():
            community = self.communities.get(connection, scope.community_id)
            day = (
                community.world_time_utc.astimezone(ZoneInfo(community.timezone)).date().isoformat()
            )
            self.thoughts.add(
                connection,
                result_id,
                scope.community_id,
                scope.character_id,
                scope.conversation_id,
                day,
                proposal.thought,
                now,
            )
        return message, batch_id
