import sqlite3
from dataclasses import replace
from datetime import UTC, datetime
from uuid import uuid4

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.domain.conversation import Conversation, Membership
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.input_batches import InputBatchRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.continuation import ContinuationPolicy
from echo_commons.modules.social.contracts import ResponseRequest, ResponseTaskPort
from echo_commons.modules.social.domain import (
    ParticipationDecision,
    ParticipationStatus,
    SocialChain,
    SocialTurn,
    TurnStatus,
)
from echo_commons.modules.social.eligibility import ParticipationEligibility
from echo_commons.modules.social.events import turns_changed
from echo_commons.modules.social.participation import (
    Candidate,
    ParticipationPolicy,
    RuleBasedParticipationPolicy,
)
from echo_commons.modules.social.repository import SocialRepository
from echo_commons.shared.actors import ActorKind


class TurnPlanner:
    def __init__(
        self,
        database: Database,
        communities: CommunityRepository,
        conversations: ConversationRepository,
        instances: InstanceRepository,
        messages: MessageRepository,
        batches: InputBatchRepository,
        social: SocialRepository,
        tasks: ResponseTaskPort,
        perspective: PerspectiveReader,
        completion: TurnCompletion,
        *,
        continuation: ContinuationPolicy | None = None,
        participation: ParticipationPolicy | None = None,
    ) -> None:
        self.database, self.communities, self.conversations = database, communities, conversations
        self.messages, self.batches, self.social = messages, batches, social
        self.tasks, self.perspective, self.completion = tasks, perspective, completion
        self.continuation = continuation or ContinuationPolicy()
        self.participation = participation or RuleBasedParticipationPolicy()
        self.eligibility = ParticipationEligibility(instances, perspective)

    def plan(self) -> tuple[str, ...]:
        progressed = []
        with self.database.transaction() as connection:
            self.batches.seal_due(connection, datetime.now(UTC))
            scopes = dict.fromkeys(
                (row["community_id"], row["conversation_id"])
                for row in connection.execute(
                    "SELECT community_id,conversation_id FROM social_chains WHERE status='active' "
                    "UNION SELECT community_id,conversation_id FROM social_turns "
                    "WHERE status='pending' AND initiation_id IS NOT NULL"
                )
            )
            scopes.update(
                dict.fromkeys(
                    (row["community_id"], row["conversation_id"])
                    for row in self.batches.awaiting(connection)
                )
            )
            for community_id, conversation_id in scopes:
                conversation = self.conversations.get(connection, community_id, conversation_id)
                if conversation.status != "active":
                    continue
                if self.communities.get(connection, community_id).status != "active":
                    continue
                if conversation.kind in ("group", "game"):
                    turn_id = self._plan_round(connection, conversation)
                else:
                    turn_id = self._plan_direct(connection, conversation)
                if turn_id:
                    progressed.append(turn_id)
        return tuple(progressed)

    def _round(self, connection, conversation) -> SocialChain:
        chain = self.social.active_chain(connection, conversation.conversation_id)
        if chain is None:
            chain = SocialChain(
                str(uuid4()),
                conversation.community_id,
                conversation.conversation_id,
                self.continuation.max_messages,
                self.continuation.max_tasks,
                0,
                0,
                "active",
                None,
                datetime.now(UTC),
                None,
            )
            self.social.add_chain(connection, chain)
        # 玩家收集窗口中的消息也属于当前轮次，结束后不会再次开启一轮。
        for row in connection.execute(
            "SELECT b.input_batch_id FROM input_batches b WHERE b.conversation_id=? "
            "AND b.sender_kind='player' AND NOT EXISTS "
            "(SELECT 1 FROM social_chain_batches r WHERE r.input_batch_id=b.input_batch_id) "
            "AND NOT EXISTS (SELECT 1 FROM social_turn_batches s "
            "WHERE s.input_batch_id=b.input_batch_id)",
            (conversation.conversation_id,),
        ).fetchall():
            self.social.attach_batch(connection, chain.chain_id, row[0])
        return chain

    def initiate(
        self,
        connection: sqlite3.Connection,
        conversation: Conversation,
        member: Membership,
        initiation_id: str,
        audience: tuple[str, ...],
        at: datetime,
    ) -> str:
        existing = self.social.active_chain(connection, conversation.conversation_id)
        if (
            existing
            and (reason := ContinuationPolicy.stop_reason(existing))
            and not self.social.running(connection, conversation.conversation_id)
        ):
            self._close_round(connection, existing, reason)
        chain = (
            self._round(connection, conversation)
            if conversation.kind in ("group", "game")
            else None
        )
        turn = self._new_turn(
            connection,
            conversation,
            (),
            audience,
            "conversation",
            chain=chain,
            initiation_id=initiation_id,
        )
        self._select(connection, turn, member, "initiation", at)
        task_id = self.tasks.reserve(connection, turn, member, at)
        if self.communities.get(
            connection, conversation.community_id
        ).status == "active" and not self.social.running(connection, conversation.conversation_id):
            self._activate_initiation(connection, conversation, chain)
        turns_changed(connection, turn.social_turn_id)
        return task_id

    def _messages(self, connection, conversation_id, identities) -> tuple[Message, ...]:
        return tuple(
            self.messages.get(connection, conversation_id, identity) for identity in identities
        )

    def _unseen(self, connection, conversation, chain, member, messages) -> tuple[Message, ...]:
        considered = self.social.considered(connection, chain.chain_id, member.membership_id)
        scope = ObservationScope(
            conversation.community_id,
            conversation.conversation_id,
            member.actor,
            conversation.next_sequence - 1,
            member.membership_id,
        )
        return tuple(
            message
            for message in messages
            if message.sequence > considered
            and message.sender != member.actor
            and self.perspective.visible(connection, scope, message)
        )

    def _collecting(self, connection, conversation_id) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM input_batches WHERE conversation_id=? AND status='collecting'",
                (conversation_id,),
            ).fetchone()
            is not None
        )

    def _activate_initiation(self, connection, conversation, chain) -> str | None:
        if self.social.running(connection, conversation.conversation_id):
            return None
        if self._collecting(connection, conversation.conversation_id):
            return None
        if chain and ContinuationPolicy.stop_reason(chain):
            self._close_round(connection, chain, ContinuationPolicy.stop_reason(chain))
            return None
        row = connection.execute(
            "SELECT s.social_turn_id FROM social_turns s "
            "WHERE s.conversation_id=? AND s.status='pending' AND s.initiation_id IS NOT NULL "
            "ORDER BY s.created_at_utc,s.social_turn_id LIMIT 1",
            (conversation.conversation_id,),
        ).fetchone()
        if row is None:
            return None
        reserved = self.tasks.reservation(connection, row["social_turn_id"])
        if reserved is None:
            return None
        turn = self.social.by_id(connection, row["social_turn_id"])
        member = next(
            item
            for item in self.conversations.members(
                connection, conversation.conversation_id, current_only=False
            )
            if item.membership_id == reserved.membership_id
        )
        turn = replace(
            turn,
            observation_max_sequence=conversation.next_sequence - 1,
            membership_version=conversation.membership_version,
            status=TurnStatus.RUNNING,
        )
        reason = self.eligibility.reason(connection, turn, member, member.membership_id, ())
        if reason:
            self.tasks.cancel_turn(connection, turn.social_turn_id, reason, datetime.now(UTC))
            self.social.cancel_turn(connection, turn.social_turn_id, reason, datetime.now(UTC))
            turns_changed(connection, turn.social_turn_id)
            return turn.social_turn_id
        inputs = (
            self._unseen(
                connection,
                conversation,
                chain,
                member,
                self._messages(
                    connection,
                    conversation.conversation_id,
                    self.social.round_messages(connection, chain.chain_id),
                ),
            )
            if chain
            else ()
        )
        current_audience = set(turn.audience) & {
            item.membership_id
            for item in self.conversations.members(connection, conversation.conversation_id)
        }
        inputs = tuple(message for message in inputs if current_audience <= set(message.audience))
        connection.execute(
            "UPDATE social_turns SET status='running',observation_max_sequence=?,"
            "membership_version=? "
            "WHERE social_turn_id=?",
            (turn.observation_max_sequence, turn.membership_version, turn.social_turn_id),
        )
        self.social.link_sources(
            connection, turn.social_turn_id, self._batch_ids(connection, inputs)
        )
        self._dispatch(connection, turn, member, inputs, task_id=reserved.reference_id)
        turns_changed(connection, turn.social_turn_id)
        return turn.social_turn_id

    def _plan_round(self, connection, conversation) -> str | None:
        chain = self._round(connection, conversation)
        if self.social.running(connection, conversation.conversation_id):
            return None
        reason = ContinuationPolicy.stop_reason(chain)
        if reason:
            self._close_round(connection, chain, reason)
            return None
        if self._collecting(connection, conversation.conversation_id):
            return None
        initiated = self._activate_initiation(connection, conversation, chain)
        if initiated:
            return initiated
        messages = self._messages(
            connection,
            conversation.conversation_id,
            self.social.round_messages(connection, chain.chain_id),
        )
        choices, details, excluded = [], {}, {}
        members = self.conversations.members(connection, conversation.conversation_id)
        for member in members:
            if member.actor.kind is not ActorKind.CHARACTER:
                continue
            inputs = self._unseen(connection, conversation, chain, member, messages)
            if not inputs:
                continue
            audience, visibility = self._audience(inputs)
            turn = self._draft(conversation, audience, visibility, chain=chain)
            reason = self.eligibility.reason(connection, turn, member, member.membership_id, inputs)
            if reason:
                excluded[member.actor.actor_id] = reason
                continue
            mentioned = any(member.actor in message.mentions for message in inputs)
            replied = any(
                message.reply_to_message_id
                and self.messages.get(
                    connection, conversation.conversation_id, message.reply_to_message_id
                ).sender
                == member.actor
                for message in inputs
            )
            choices.append(
                Candidate(
                    member.actor.actor_id,
                    mentioned,
                    self.messages.last_spoke(
                        connection, conversation.conversation_id, member.actor.actor_id
                    ),
                    chain_attempts=self.social.attempts(
                        connection, chain.chain_id, member.actor.actor_id
                    ),
                    replied_to=replied,
                )
            )
            details[member.actor.actor_id] = (member, inputs, audience, visibility)
        selected = self.participation.select(tuple(choices))
        if selected is None:
            if self.social.awaiting_expression(connection, chain.chain_id):
                return None
            self._close_round(connection, chain, "no_eligible_candidates" if excluded else "quiet")
            return None
        member, inputs, audience, visibility = details[selected]
        turn = self._new_turn(
            connection,
            conversation,
            self._batch_ids(connection, inputs),
            audience,
            visibility,
            chain=chain,
        )
        candidate = next(item for item in choices if item.character_id == selected)
        reason = (
            "mentioned"
            if candidate.mentioned
            else "replied_to"
            if candidate.replied_to
            else "rotation"
        )
        self._select(connection, turn, member, reason, datetime.now(UTC))
        self._dispatch(connection, turn, member, inputs)
        turns_changed(connection, turn.social_turn_id)
        return turn.social_turn_id

    def _plan_direct(self, connection, conversation) -> str | None:
        if self.social.running(connection, conversation.conversation_id):
            return None
        initiated = self._activate_initiation(connection, conversation, None)
        if initiated or conversation.kind == "game":
            return initiated
        if self._collecting(connection, conversation.conversation_id):
            return None
        batches = [
            row
            for row in self.batches.awaiting(connection)
            if row["conversation_id"] == conversation.conversation_id
        ]
        if not batches:
            return None
        inputs = self._messages(
            connection,
            conversation.conversation_id,
            tuple(
                identity
                for row in batches
                for identity in self.batches.message_ids(connection, row["input_batch_id"])
            ),
        )
        audience, visibility = self._audience(inputs)
        turn = self._new_turn(
            connection,
            conversation,
            tuple(row["input_batch_id"] for row in batches),
            audience,
            visibility,
        )
        if any(
            connection.execute(
                "SELECT left_at_utc FROM conversation_memberships WHERE membership_id=?",
                (message.sender_membership_id,),
            ).fetchone()[0]
            is not None
            for message in inputs
        ):
            self.social.cancel_turn(
                connection, turn.social_turn_id, "member_left", datetime.now(UTC)
            )
            turns_changed(connection, turn.social_turn_id)
            return turn.social_turn_id
        for member in self.conversations.members(connection, conversation.conversation_id):
            if member.actor.kind is ActorKind.CHARACTER:
                reason = self.eligibility.reason(
                    connection, turn, member, member.membership_id, inputs
                )
                if reason:
                    self.social.decision(
                        connection,
                        ParticipationDecision(
                            turn.social_turn_id,
                            member.actor.actor_id,
                            reason,
                            None,
                            ParticipationStatus.SILENT,
                            "silent",
                            datetime.now(UTC),
                        ),
                    )
                else:
                    self._select(connection, turn, member, "direct", datetime.now(UTC))
                    self._dispatch(connection, turn, member, inputs)
        self.completion.update(connection, turn.social_turn_id, datetime.now(UTC))
        turns_changed(connection, turn.social_turn_id)
        return turn.social_turn_id

    @staticmethod
    def _audience(inputs):
        audience = set(inputs[0].audience)
        for message in inputs[1:]:
            audience.intersection_update(message.audience)
        return tuple(sorted(audience)), "recipients" if any(
            message.visibility == "recipients" for message in inputs
        ) else "conversation"

    @staticmethod
    def _batch_ids(connection, inputs):
        return tuple(
            dict.fromkeys(
                connection.execute(
                    "SELECT input_batch_id FROM input_batch_messages WHERE message_id=?",
                    (message.message_id,),
                ).fetchone()[0]
                for message in inputs
            )
        )

    def _draft(self, conversation, audience, visibility, *, chain=None, initiation_id=None):
        return SocialTurn(
            str(uuid4()),
            conversation.community_id,
            conversation.conversation_id,
            audience,
            visibility,
            conversation.next_sequence - 1,
            conversation.membership_version,
            TurnStatus.PENDING if initiation_id else TurnStatus.RUNNING,
            datetime.now(UTC),
            None,
            chain.chain_id if chain else None,
            self.participation.version,
            initiation_id=initiation_id,
        )

    def _new_turn(self, connection, conversation, batch_ids, audience, visibility, **kwargs):
        turn = self._draft(conversation, audience, visibility, **kwargs)
        self.social.add(connection, turn, batch_ids)
        return turn

    def _select(self, connection, turn, member, reason, at):
        self.social.decision(
            connection,
            ParticipationDecision(
                turn.social_turn_id,
                member.actor.actor_id,
                reason,
                0,
                ParticipationStatus.SELECTED,
                None,
                at,
            ),
        )

    def _dispatch(self, connection, turn, member, inputs, *, task_id=None):
        if turn.chain_id:
            self.social.task_created(connection, turn.chain_id)
        dispatch = self.tasks.create(
            connection, ResponseRequest(turn, member, inputs, datetime.now(UTC)), task_id=task_id
        )
        if dispatch.failure_code:
            self.social.complete_participation(
                connection,
                turn.social_turn_id,
                member.actor.actor_id,
                "failed",
                "failed",
                datetime.now(UTC),
            )
            if turn.chain_id:
                self.social.observe(
                    connection, turn.chain_id, member.membership_id, turn.observation_max_sequence
                )
            self.completion.update(connection, turn.social_turn_id, datetime.now(UTC))
            if turn.chain_id:
                chain = self.social.chain(connection, turn.chain_id)
                if reason := ContinuationPolicy.stop_reason(chain):
                    self._close_round(connection, chain, reason)
        return dispatch

    def _close_round(self, connection, chain, reason):
        self.completion.close_round(connection, chain, reason, datetime.now(UTC), self.tasks)
