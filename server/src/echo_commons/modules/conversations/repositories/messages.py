from __future__ import annotations

import sqlite3

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.conversations.domain.message import Message, MessageVisibility
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.message_sources import SystemSource, message_source_id


class MessageRepository:
    def last_spoke(self, connection: sqlite3.Connection, conversation_id: str, character_id: str):
        row = connection.execute(
            "SELECT MAX(created_at_utc) FROM messages WHERE conversation_id = ? AND "
            "sender_kind = 'character' AND sender_id = ?",
            (conversation_id, character_id),
        ).fetchone()
        return utc_datetime(row[0]) if row[0] else None

    def get(self, connection: sqlite3.Connection, conversation_id: str, message_id: str) -> Message:
        row = connection.execute(
            "SELECT * FROM messages WHERE conversation_id = ? AND message_id = ?",
            (conversation_id, message_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Message does not exist in this conversation")
        return self.from_row(connection, row)

    def from_row(self, connection: sqlite3.Connection, row: sqlite3.Row) -> Message:
        audience = tuple(
            item[0]
            for item in connection.execute(
                "SELECT membership_id FROM message_recipients WHERE message_id = ? ORDER "
                "BY membership_id",
                (row["message_id"],),
            )
        )
        mentions = tuple(
            ActorRef(item[0], item[1])
            for item in connection.execute(
                "SELECT actor_kind, actor_id FROM message_mentions "
                "WHERE message_id = ? ORDER BY ordinal",
                (row["message_id"],),
            )
        )
        return Message(
            row["message_id"],
            row["community_id"],
            row["conversation_id"],
            row["sequence"],
            SystemSource(row["sender_id"])
            if row["sender_kind"] == "system"
            else ActorRef(row["sender_kind"], row["sender_id"]),
            row["sender_membership_id"],
            row["text"],
            MessageVisibility(row["visibility"]),
            audience,
            mentions,
            row["reply_to_message_id"],
            row["client_message_id"],
            row["source_turn_id"],
            row["result_id"],
            row["trace_id"],
            utc_datetime(row["created_at_utc"]),
        )

    def by_client(
        self, connection: sqlite3.Connection, player_id: str, client_id: str
    ) -> Message | None:
        row = connection.execute(
            "SELECT * FROM messages WHERE sender_kind = 'player' AND sender_id = ? "
            "AND client_message_id = ?",
            (player_id, client_id),
        ).fetchone()
        return self.from_row(connection, row) if row else None

    def audience_actors(
        self, connection: sqlite3.Connection, message: Message
    ) -> frozenset[ActorRef]:
        return frozenset(
            ActorRef(row[0], row[1])
            for row in connection.execute(
                "SELECT cm.actor_kind, cm.actor_id FROM message_recipients mr "
                "JOIN conversation_memberships cm ON cm.membership_id = mr.membership_id "
                "WHERE mr.message_id = ?",
                (message.message_id,),
            )
        )

    def add(self, connection: sqlite3.Connection, message: Message) -> None:
        connection.execute(
            "INSERT INTO messages VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                message.message_id,
                message.community_id,
                message.conversation_id,
                message.sequence,
                message.sender.kind.value,
                message_source_id(message.sender),
                message.sender_membership_id,
                message.text,
                message.visibility.value,
                message.reply_to_message_id,
                message.client_message_id,
                message.source_turn_id,
                message.result_id,
                message.trace_id,
                utc_text(message.created_at_utc),
            ),
        )
        connection.executemany(
            "INSERT INTO message_recipients VALUES (?, ?)",
            [(message.message_id, membership_id) for membership_id in message.audience],
        )
        connection.executemany(
            "INSERT INTO message_mentions VALUES (?, ?, ?, ?)",
            [
                (message.message_id, actor.kind.value, actor.actor_id, index)
                for index, actor in enumerate(message.mentions)
            ],
        )

    def scan(
        self,
        connection: sqlite3.Connection,
        conversation_id: str,
        after: int,
        upper: int,
        limit: int,
    ) -> tuple[Message, ...]:
        return tuple(
            self.from_row(connection, row)
            for row in connection.execute(
                "SELECT * FROM messages WHERE conversation_id = ? AND sequence > ? AND "
                "sequence <= ? ORDER BY sequence LIMIT ?",
                (conversation_id, after, upper, limit),
            )
        )
