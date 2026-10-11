import json
import sqlite3
from datetime import UTC, datetime
from uuid import uuid4

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.input_batches import InputBatchRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.perspective.contracts import PerspectiveReader
from echo_commons.modules.social.completion import TurnCompletion
from echo_commons.modules.social.continuation import ContinuationPolicy
from echo_commons.modules.social.contracts import ConversationTaskPort, ResponseRequest
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
        tasks: ConversationTaskPort,
        perspective: PerspectiveReader,
        completion: TurnCompletion,
        *,
        continuation: ContinuationPolicy | None = None,
        participation: ParticipationPolicy | None = None,
    ) -> None:
        self.database, self.communities, self.conversations = database, communities, conversations
        self.messages, self.batches, self.social = messages, batches, social
        self.tasks, self.completion = tasks, completion
        self.continuation = continuation or ContinuationPolicy()
        self.participation = participation or RuleBasedParticipationPolicy()
        self.eligibility = ParticipationEligibility(instances, perspective)

    def plan(self) -> tuple[str, ...]:
        progressed = []
        with self.database.transaction() as connection:
            self.batches.seal_due(connection, datetime.now(UTC))
            # 沉默与失败只登记结果，由下一次规划继续选择。
            for turn in self.social.active_turns(connection):
                if self._advance(connection, turn):
                    progressed.append(turn.social_turn_id)
            scopes = dict.fromkeys(
                (
                    batch["community_id"],
                    batch["conversation_id"],
                    batch["visibility"],
                    batch["audience_json"],
                )
                for batch in self.batches.awaiting(connection)
            )
            for scope in scopes:
                turn_id = self._plan_group(connection, scope)
                if turn_id:
                    progressed.append(turn_id)
            for trigger in self.social.pending_triggers(connection):
                chain = self.social.chain(connection, trigger["chain_id"])
                if not self._available(connection, chain.community_id, chain.conversation_id):
                    continue
                if self.social.running(connection, chain.conversation_id):
                    continue
                parent = self.social.by_id(connection, trigger["origin_turn_id"])
                inputs = self._messages(
                    connection,
                    chain.conversation_id,
                    self.batches.message_ids(connection, trigger["input_batch_id"]),
                )
                conversation = self.conversations.get(
                    connection,
                    chain.community_id,
                    chain.conversation_id,
                )
                turn = self._new_turn(
                    connection,
                    conversation,
                    inputs,
                    (trigger["input_batch_id"],),
                    chain_id=chain.chain_id,
                    parent=parent,
                )
                self.social.consume_trigger(connection, trigger["input_batch_id"])
                self._advance(connection, turn)
                progressed.append(turn.social_turn_id)
            for turn_id in progressed:
                turns_changed(connection, turn_id)
        return tuple(progressed)

    def _available(self, connection, community_id, conversation_id):
        return (
            self.communities.get(connection, community_id).status == "active"
            and self.conversations.get(connection, community_id, conversation_id).status == "active"
        )

    def _messages(self, connection, conversation_id, identities) -> tuple[Message, ...]:
        return tuple(
            sorted(
                (
                    self.messages.get(connection, conversation_id, identity)
                    for identity in identities
                ),
                key=lambda item: item.sequence,
            )
        )

    def _plan_group(self, connection, scope) -> str | None:
        community_id, conversation_id, visibility, audience_json = scope
        if not self._available(connection, community_id, conversation_id):
            return None
        if self.social.running(connection, conversation_id):
            return None
        batches = self.batches.awaiting(connection, scope=scope)
        if not batches:
            return None
        if connection.execute(
            "SELECT 1 FROM input_batches WHERE conversation_id=? AND status='collecting'",
            (conversation_id,),
        ).fetchone():
            return None
        inputs = self._messages(
            connection,
            conversation_id,
            (
                identity
                for batch in batches
                for identity in self.batches.message_ids(connection, batch["input_batch_id"])
            ),
        )
        if not inputs or any(
            item.audience != tuple(json.loads(audience_json)) or item.visibility.value != visibility
            for item in inputs
        ):
            raise ValueError("Input batch sources disagree with their audience")
        conversation = self.conversations.get(connection, community_id, conversation_id)
        turn = self._new_turn(
            connection,
            conversation,
            inputs,
            tuple(batch["input_batch_id"] for batch in batches),
        )
        if any(
            connection.execute(
                "SELECT left_at_utc FROM conversation_memberships WHERE membership_id=?",
                (item.sender_membership_id,),
            ).fetchone()[0]
            is not None
            for item in inputs
        ):
            now = datetime.now(UTC)
            self.social.cancel_turn(connection, turn.social_turn_id, "member_left", now)
            if turn.chain_id:
                self.social.stop_chain(
                    connection, turn.chain_id, "member_left", now, cancelled=True
                )
            return turn.social_turn_id
        self._advance(connection, turn)
        return turn.social_turn_id

    def _new_turn(self, connection, conversation, inputs, batch_ids, *, chain_id=None, parent=None):
        now, turn_id = datetime.now(UTC), str(uuid4())
        if conversation.kind == "group" and chain_id is None:
            chain_id = str(uuid4())
            self.social.add_chain(
                connection,
                SocialChain(
                    chain_id,
                    conversation.community_id,
                    conversation.conversation_id,
                    turn_id,
                    self.continuation.max_messages,
                    self.continuation.max_tasks,
                    0,
                    0,
                    "active",
                    None,
                    now,
                    None,
                ),
            )
        turn = SocialTurn(
            turn_id,
            conversation.community_id,
            conversation.conversation_id,
            inputs[0].audience,
            inputs[0].visibility.value,
            conversation.next_sequence - 1,
            conversation.membership_version,
            TurnStatus.RUNNING,
            now,
            None,
            chain_id,
            parent.social_turn_id if parent else None,
            parent.depth + 1 if parent else 0,
            self.participation.version,
        )
        self.social.add(connection, turn, batch_ids)
        members = self.conversations.members(
            connection,
            conversation.conversation_id,
            current_only=False,
        )
        for actor, member in {member.actor: member for member in members}.items():
            if actor.kind is ActorKind.CHARACTER:
                reason = self.eligibility.reason(
                    connection,
                    turn,
                    member,
                    member.membership_id,
                    inputs,
                )
                self.social.candidate(
                    connection,
                    turn_id,
                    actor.actor_id,
                    member.membership_id,
                    reason,
                    now,
                )
        return turn

    def _advance(self, connection: sqlite3.Connection, turn: SocialTurn) -> bool:
        if not self._available(connection, turn.community_id, turn.conversation_id):
            return False
        decisions = self.social.decisions(connection, turn.social_turn_id)
        if any(item.status == "selected" for item in decisions):
            return False
        if turn.chain_id and self.completion.update(
            connection, turn.social_turn_id, datetime.now(UTC)
        ):
            return True
        inputs = self._messages(
            connection,
            turn.conversation_id,
            self.social.source_messages(connection, turn.social_turn_id),
        )
        roots = ()
        if turn.chain_id:
            chain = self.social.chain(connection, turn.chain_id)
            roots = self._messages(
                connection,
                turn.conversation_id,
                self.social.source_messages(connection, chain.root_turn_id),
            )
        members = {
            member.actor.actor_id: member
            for member in self.conversations.members(
                connection,
                turn.conversation_id,
                current_only=False,
            )
            if member.actor.kind is ActorKind.CHARACTER
        }
        mentioned = {actor for message in inputs for actor in message.mentions}
        replied = {
            self.messages.get(connection, turn.conversation_id, item.reply_to_message_id).sender
            for item in inputs
            if item.reply_to_message_id
        }
        candidates, now = [], datetime.now(UTC)
        for row in self.social.waiting(connection, turn.social_turn_id):
            member = members[row["character_id"]]
            reason = self.eligibility.reason(
                connection,
                turn,
                member,
                row["membership_id"],
                inputs + roots,
            )
            # 根输入属于背景，不能使自身刚发出的消息重新选择发送者。
            if inputs and all(item.sender == member.actor for item in inputs):
                reason = "self_trigger"
            if reason:
                self.social.mark_candidate(
                    connection,
                    turn.social_turn_id,
                    row["character_id"],
                    "excluded",
                    reason,
                )
                self.social.decision(
                    connection,
                    ParticipationDecision(
                        turn.social_turn_id,
                        row["character_id"],
                        reason,
                        None,
                        ParticipationStatus.SILENT,
                        "silent",
                        now,
                    ),
                )
                continue
            candidates.append(
                Candidate(
                    member.actor.actor_id,
                    member.actor in mentioned,
                    self.messages.last_spoke(
                        connection, turn.conversation_id, member.actor.actor_id
                    ),
                    chain_attempts=self.social.attempts(
                        connection, turn.chain_id, member.actor.actor_id
                    )
                    if turn.chain_id
                    else 0,
                    replied_to=member.actor in replied,
                )
            )
        selected = self.participation.select(tuple(candidates))
        if selected:
            candidate = next(item for item in candidates if item.character_id == selected)
            reason = (
                "mentioned"
                if candidate.mentioned
                else "replied_to"
                if candidate.replied_to
                else "rotation"
            )
            self.social.mark_candidate(
                connection, turn.social_turn_id, selected, "attempted", reason
            )
            self.social.decision(
                connection,
                ParticipationDecision(
                    turn.social_turn_id,
                    selected,
                    reason,
                    sum(item.selection_order is not None for item in decisions),
                    ParticipationStatus.SELECTED,
                    None,
                    now,
                ),
            )
            dispatch = self.tasks.create(
                connection, ResponseRequest(turn, members[selected], inputs, roots, now)
            )
            if turn.chain_id:
                self.social.task_created(connection, turn.chain_id)
            if dispatch.failure_code:
                self.social.complete_participation(
                    connection,
                    turn.social_turn_id,
                    selected,
                    "failed",
                    "failed",
                    now,
                )
                self.completion.update(connection, turn.social_turn_id, now)
        else:
            self.completion.update(connection, turn.social_turn_id, now)
        return True
