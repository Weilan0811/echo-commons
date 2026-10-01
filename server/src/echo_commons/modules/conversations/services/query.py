from __future__ import annotations

import base64
import json
from dataclasses import dataclass

from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.shared.actors import ActorRef


@dataclass(frozen=True, slots=True)
class MessagePage:
    messages: tuple[Message, ...]
    cursor: str
    has_more: bool


class MessageQuery:
    def __init__(
        self,
        database: Database,
        conversations: ConversationRepository,
        messages: MessageRepository,
        perspective: PerspectiveReader,
    ) -> None:
        self.database, self.conversations, self.messages, self.perspective = (
            database,
            conversations,
            messages,
            perspective,
        )

    def read(
        self,
        community_id: str,
        conversation_id: str,
        player_id: str,
        *,
        cursor: str | None = None,
        limit: int = 50,
    ) -> MessagePage:
        if not 1 <= limit <= 200:
            raise ValueError("Message page limit must be between 1 and 200")
        position = 0
        if cursor is not None:
            try:
                decoded = json.loads(base64.urlsafe_b64decode(cursor.encode("ascii")))
            except (ValueError, UnicodeError) as error:
                raise ValueError("Invalid message cursor") from error
            if (
                not isinstance(decoded, list)
                or len(decoded) != 4
                or decoded[:3] != [community_id, conversation_id, player_id]
            ):
                raise ValueError("Message cursor belongs to a different reader or conversation")
            position = decoded[3]
            if type(position) is not int or position < 0:
                raise ValueError("Invalid cursor scan position")
        with self.database.read() as connection:
            conversation = self.conversations.get(connection, community_id, conversation_id)
            scope = ObservationScope(
                community_id,
                conversation_id,
                ActorRef("player", player_id),
                conversation.next_sequence - 1,
            )
            # 同一策略检查历史成员资格；空会话也需要确认读取身份。
            self.perspective.messages(
                connection, ObservationScope(community_id, conversation_id, scope.actor, 0)
            )
            rows = self.messages.scan(
                connection, conversation_id, position, scope.upper_sequence, limit
            )
            visible = tuple(
                message for message in rows if self.perspective.visible(connection, scope, message)
            )
            scanned = rows[-1].sequence if rows else min(position, scope.upper_sequence)
            encoded = base64.urlsafe_b64encode(
                json.dumps(
                    [community_id, conversation_id, player_id, scanned], separators=(",", ":")
                ).encode()
            ).decode("ascii")
            return MessagePage(visible, encoded, scanned < scope.upper_sequence)
