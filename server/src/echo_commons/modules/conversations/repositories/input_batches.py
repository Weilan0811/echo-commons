from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.conversations.domain.input_batch import InputBatch
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.shared.actors import ActorRef


class InputBatchRepository:
    def collecting(self, connection: sqlite3.Connection, message: Message) -> InputBatch | None:
        row = connection.execute(
            "SELECT * FROM input_batches WHERE conversation_id = ? AND sender_kind = ? "
            "AND sender_id = ? AND visibility = ? AND audience_json = ? AND status = 'collecting'",
            (
                message.conversation_id,
                message.sender.kind.value,
                message.sender.actor_id,
                message.visibility.value,
                json.dumps(message.audience, separators=(",", ":")),
            ),
        ).fetchone()
        if row is None:
            return None
        return InputBatch(
            row["input_batch_id"],
            row["community_id"],
            row["conversation_id"],
            ActorRef(row["sender_kind"], row["sender_id"]),
            row["visibility"],
            tuple(json.loads(row["audience_json"])),
            row["status"],
            utc_datetime(row["quiet_until_utc"]),
            utc_datetime(row["sealed_at_utc"]) if row["sealed_at_utc"] else None,
            row["origin_turn_id"],
            utc_datetime(row["created_at_utc"]),
            utc_datetime(row["updated_at_utc"]),
        )

    def add(self, connection: sqlite3.Connection, batch: InputBatch) -> None:
        connection.execute(
            "INSERT INTO input_batches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                batch.input_batch_id,
                batch.community_id,
                batch.conversation_id,
                batch.sender.kind.value,
                batch.sender.actor_id,
                batch.visibility.value,
                json.dumps(batch.audience, separators=(",", ":")),
                batch.status,
                utc_text(batch.quiet_until_utc),
                utc_text(batch.sealed_at_utc) if batch.sealed_at_utc else None,
                batch.origin_turn_id,
                utc_text(batch.created_at_utc),
                utc_text(batch.updated_at_utc),
            ),
        )

    def extend(
        self, connection: sqlite3.Connection, batch_id: str, until: datetime, now: datetime
    ) -> None:
        connection.execute(
            "UPDATE input_batches SET quiet_until_utc = ?, updated_at_utc = ? WHERE "
            "input_batch_id = ?",
            (utc_text(until), utc_text(now), batch_id),
        )

    def seal(self, connection: sqlite3.Connection, batch_id: str, now: datetime) -> None:
        connection.execute(
            "UPDATE input_batches SET status = 'sealed', sealed_at_utc = ?, "
            "updated_at_utc = ? WHERE input_batch_id = ? AND status = 'collecting'",
            (utc_text(now), utc_text(now), batch_id),
        )

    def link(self, connection: sqlite3.Connection, batch_id: str, message_id: str) -> None:
        connection.execute("INSERT INTO input_batch_messages VALUES (?, ?)", (batch_id, message_id))

    def awaiting(self, connection: sqlite3.Connection) -> tuple[sqlite3.Row, ...]:
        query = (
            "SELECT b.* FROM input_batches b WHERE b.sender_kind = 'player' "
            "AND EXISTS (SELECT 1 FROM conversations c WHERE c.conversation_id=b.conversation_id "
            "AND c.kind IN ('direct','group')) "
            "AND b.status = 'sealed' AND NOT EXISTS (SELECT 1 FROM social_turn_batches st "
            "WHERE st.input_batch_id = b.input_batch_id) "
            "AND NOT EXISTS (SELECT 1 FROM social_chain_batches r "
            "WHERE r.input_batch_id=b.input_batch_id) "
        )
        return tuple(connection.execute(query + "ORDER BY b.created_at_utc, b.input_batch_id"))

    def message_ids(self, connection: sqlite3.Connection, batch_id: str) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in connection.execute(
                "SELECT bm.message_id FROM input_batch_messages bm JOIN messages m ON "
                "m.message_id = bm.message_id "
                "WHERE bm.input_batch_id = ? ORDER BY m.sequence",
                (batch_id,),
            )
        )

    def seal_due(self, connection: sqlite3.Connection, at: datetime) -> int:
        now = utc_text(at)
        return connection.execute(
            "UPDATE input_batches SET status = 'sealed', sealed_at_utc = ?, "
            "updated_at_utc = ? WHERE status = 'collecting' AND quiet_until_utc <= ?",
            (now, now, now),
        ).rowcount
