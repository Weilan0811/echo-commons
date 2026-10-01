from __future__ import annotations

import sqlite3

from echo_commons.infrastructure.database.mapping import utc_datetime
from echo_commons.modules.conversations.domain.conversation import (
    Conversation,
    ConversationKind,
    ConversationStatus,
    Membership,
)
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


class ConversationRepository:
    def for_actor(
        self, connection: sqlite3.Connection, community_id: str, actor: ActorRef
    ) -> tuple[Conversation, ...]:
        return tuple(
            self.get(connection, community_id, row[0])
            for row in connection.execute(
                "SELECT DISTINCT conversation_id FROM conversation_memberships WHERE "
                "community_id = ? AND actor_kind = ? AND actor_id = ?",
                (community_id, actor.kind.value, actor.actor_id),
            )
        )

    def get(
        self, connection: sqlite3.Connection, community_id: str, conversation_id: str
    ) -> Conversation:
        row = connection.execute(
            "SELECT * FROM conversations WHERE community_id = ? AND conversation_id = ?",
            (community_id, conversation_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Conversation does not exist in this community")
        return Conversation(
            row["conversation_id"],
            row["community_id"],
            ConversationKind(row["kind"]),
            ConversationStatus(row["status"]),
            row["membership_version"],
            row["next_sequence"],
            utc_datetime(row["created_at_utc"]),
            utc_datetime(row["updated_at_utc"]),
        )

    def membership(self, row: sqlite3.Row) -> Membership:
        return Membership(
            row["membership_id"],
            row["community_id"],
            row["conversation_id"],
            ActorRef(row["actor_kind"], row["actor_id"]),
            row["joined_after_sequence"],
            row["left_at_sequence"],
            utc_datetime(row["joined_at_utc"]),
            utc_datetime(row["left_at_utc"]) if row["left_at_utc"] else None,
        )

    def members(
        self, connection: sqlite3.Connection, conversation_id: str, *, current_only: bool = True
    ) -> tuple[Membership, ...]:
        query = "SELECT * FROM conversation_memberships WHERE conversation_id = ?"
        if current_only:
            query += " AND left_at_utc IS NULL"
        return tuple(
            self.membership(row)
            for row in connection.execute(
                query + " ORDER BY joined_at_utc, membership_id", (conversation_id,)
            )
        )

    def current(
        self, connection: sqlite3.Connection, conversation_id: str, actor: ActorRef
    ) -> Membership:
        row = connection.execute(
            "SELECT * FROM conversation_memberships WHERE conversation_id = ? AND "
            "actor_kind = ? AND actor_id = ? AND left_at_utc IS NULL",
            (conversation_id, actor.kind.value, actor.actor_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Actor has no current conversation membership")
        return self.membership(row)
