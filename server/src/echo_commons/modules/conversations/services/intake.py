from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.infrastructure.observability.outbox import enqueue_trace
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.conversations.domain.conversation import ConversationStatus
from echo_commons.modules.conversations.domain.message import (
    Message,
    MessageVisibility,
    PlayerMessage,
)
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.conversations.services.batching import InputCollector
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.shared.actors import ActorKind, ActorRef
from echo_commons.shared.errors import ConflictError, NotFoundError


class MessageIndexer(Protocol):
    def message(self, connection: sqlite3.Connection, message: Message) -> None: ...


class MessageIntake:
    def __init__(
        self,
        database: Database,
        communities: CommunityReader,
        conversations: ConversationRepository,
        messages: MessageRepository,
        perspective: PerspectiveReader,
        batches: InputCollector,
        indexer: MessageIndexer,
        *,
        quiet_seconds: float = 6,
    ) -> None:
        if quiet_seconds < 0:
            raise ValueError("Quiet window must be nonnegative")
        self.database, self.communities, self.conversations = database, communities, conversations
        self.messages, self.perspective, self.batches, self.indexer = (
            messages,
            perspective,
            batches,
            indexer,
        )
        self.quiet_seconds = quiet_seconds

    def send(self, community_id: str, conversation_id: str, request: PlayerMessage) -> Message:
        sender = ActorRef(ActorKind.PLAYER, request.player_id)
        with self.database.transaction() as connection:
            now = datetime.now(UTC)
            # 幂等比较使用原始受众，发送者离开以后仍能得到原来的确认。
            existing = self.messages.by_client(
                connection, request.player_id, request.client_message_id
            )
            if existing:
                original_audience = self.messages.audience_actors(connection, existing)
                expected_audience = frozenset(request.recipients) | {sender}
                same = (
                    existing.community_id == community_id
                    and existing.conversation_id == conversation_id
                    and existing.text == request.text
                    and existing.visibility == request.visibility
                    and existing.reply_to_message_id == request.reply_to_message_id
                    and existing.mentions == request.mentions
                    and (
                        request.visibility is MessageVisibility.CONVERSATION
                        or original_audience == expected_audience
                    )
                )
                if not same:
                    raise ConflictError("Client message ID already records a different request")
                return existing
            self.communities.require_member(connection, community_id, sender)
            conversation = self.conversations.get(connection, community_id, conversation_id)
            if conversation.status is not ConversationStatus.ACTIVE:
                raise ConflictError("Archived conversation does not accept messages")
            membership = self.conversations.current(connection, conversation_id, sender)
            members = self.conversations.members(connection, conversation_id)
            by_actor = {member.actor: member for member in members}
            for actor in request.recipients + request.mentions:
                if actor not in by_actor:
                    raise NotFoundError("Recipient or mention is not a current conversation member")
            if request.reply_to_message_id:
                target = self.messages.get(connection, conversation_id, request.reply_to_message_id)
                scope = ObservationScope(
                    community_id,
                    conversation_id,
                    sender,
                    conversation.next_sequence - 1,
                    membership.membership_id,
                )
                if not self.perspective.visible(connection, scope, target):
                    raise NotFoundError("Reply target is not visible to the sender")
            if request.visibility is MessageVisibility.CONVERSATION:
                audience = tuple(sorted(member.membership_id for member in members))
            else:
                audience = tuple(
                    sorted(
                        {membership.membership_id}
                        | {by_actor[actor].membership_id for actor in request.recipients}
                    )
                )
            message = Message(
                str(uuid4()),
                community_id,
                conversation_id,
                conversation.next_sequence,
                sender,
                membership.membership_id,
                request.text,
                request.visibility,
                audience,
                request.mentions,
                request.reply_to_message_id,
                request.client_message_id,
                None,
                None,
                str(uuid4()),
                now,
            )
            self.messages.add(connection, message)
            connection.execute(
                "UPDATE conversations SET next_sequence = next_sequence + 1, "
                "updated_at_utc = ? WHERE conversation_id = ?",
                (utc_text(now), conversation_id),
            )
            self.batches.collect(connection, message, self.quiet_seconds)
            self.indexer.message(connection, message)
            enqueue_trace(
                connection,
                message.trace_id,
                message.message_id,
                "message_committed",
                "message",
                message.message_id,
                {
                    "community_id": community_id,
                    "conversation_id": conversation_id,
                    "sequence": message.sequence,
                    "sender_kind": "player",
                },
                now,
            )
            return message
