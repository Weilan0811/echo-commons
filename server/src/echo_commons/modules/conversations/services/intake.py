from __future__ import annotations

import sqlite3
from datetime import UTC, datetime
from typing import Protocol
from uuid import uuid4

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.observability.outbox import enqueue_trace
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.conversations.contracts import GameConversationAccess
from echo_commons.modules.conversations.domain.conversation import (
    ConversationKind,
    ConversationStatus,
)
from echo_commons.modules.conversations.domain.message import (
    Message,
    MessageVisibility,
    PlayerMessage,
)
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.conversations.services.batching import InputCollector
from echo_commons.modules.conversations.services.events import message_created
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.modules.social.contracts import SocialLifecyclePort
from echo_commons.shared.actors import ActorKind, ActorRef
from echo_commons.shared.errors import (
    ConflictError,
    ConversationArchived,
    IdempotencyConflict,
    NotFoundError,
)


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
        social: SocialLifecyclePort,
        game_access: GameConversationAccess,
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
        self.social = social
        self.game_access = game_access

    def send(self, community_id: str, conversation_id: str, request: PlayerMessage) -> Message:
        sender = ActorRef(ActorKind.PLAYER, request.player_id)
        with self.database.transaction() as connection:
            now = datetime.now(UTC)
            # 重复请求先检查原事实，成员变化后仍可返回原确认。
            existing = self.messages.by_client(
                connection, request.player_id, request.client_message_id
            )
            if existing:
                same = (
                    existing.community_id == community_id
                    and existing.conversation_id == conversation_id
                    and existing.text == request.text
                    and existing.visibility is MessageVisibility.CONVERSATION
                    and existing.reply_to_message_id == request.reply_to_message_id
                    and existing.mentions == request.mentions
                )
                if not same:
                    raise IdempotencyConflict(
                        "Client message ID already records a different request"
                    )
                return existing
            self.communities.require_member(connection, community_id, sender)
            conversation = self.conversations.get(connection, community_id, conversation_id)
            if conversation.status is not ConversationStatus.ACTIVE:
                raise ConversationArchived("Archived conversation does not accept messages")
            membership = self.conversations.current(connection, conversation_id, sender)
            if conversation.kind is ConversationKind.GAME and not self.game_access.can_send(
                connection, community_id, conversation_id, sender
            ):
                raise ConflictError("Game does not accept new conversation messages")
            members = self.conversations.members(connection, conversation_id)
            by_actor = {member.actor: member for member in members}
            for actor in request.mentions:
                if actor not in by_actor:
                    raise NotFoundError("Mention is not a current conversation member")
            if request.reply_to_message_id:
                target = self.messages.get(connection, conversation_id, request.reply_to_message_id)
                scope = ObservationScope(
                    community_id,
                    conversation_id,
                    sender,
                    conversation.next_sequence - 1,
                )
                if not self.perspective.visible(connection, scope, target):
                    raise NotFoundError("Reply target is not visible to the sender")
            audience = tuple(sorted(member.membership_id for member in members))
            message = Message(
                str(uuid4()),
                community_id,
                conversation_id,
                self.conversations.allocate_sequence(connection, conversation_id, now),
                sender,
                membership.membership_id,
                request.text,
                MessageVisibility.CONVERSATION,
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
            message_created(connection, message)
            self.batches.collect(connection, message, self.quiet_seconds)
            self.social.message_received(connection, message)
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
