from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.conversations.domain.message import Message


class InputBatchRepository:
    def collect(
        self, connection: sqlite3.Connection, message: Message, quiet_seconds: float
    ) -> str:
        audience = json.dumps(sorted(message.audience), separators=(",", ":"))
        now = utc_text(message.created_at_utc)
        scope = (
            message.conversation_id,
            message.sender.kind.value,
            message.sender.actor_id,
            message.visibility.value,
            audience,
        )
        existing = connection.execute(
            "SELECT * FROM input_batches WHERE conversation_id = ? AND sender_kind = "
            "? AND sender_id = ? AND visibility = ? AND audience_json = ? AND status "
            "= 'collecting'",
            scope,
        ).fetchone()
        if existing and existing["quiet_until_utc"] <= now:
            connection.execute(
                "UPDATE input_batches SET status = 'sealed', sealed_at_utc = ?, "
                "updated_at_utc = ? WHERE input_batch_id = ?",
                (now, now, existing["input_batch_id"]),
            )
            existing = None
        zero_window = quiet_seconds == 0
        quiet_until = utc_text(message.created_at_utc + timedelta(seconds=quiet_seconds))
        if existing:
            batch_id = existing["input_batch_id"]
            connection.execute(
                "UPDATE input_batches SET quiet_until_utc = ?, updated_at_utc = ? WHERE "
                "input_batch_id = ?",
                (quiet_until, now, batch_id),
            )
        else:
            batch_id = str(uuid4())
            connection.execute(
                "INSERT INTO input_batches VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    batch_id,
                    message.community_id,
                    message.conversation_id,
                    message.sender.kind.value,
                    message.sender.actor_id,
                    message.visibility.value,
                    audience,
                    "sealed" if zero_window else "collecting",
                    quiet_until,
                    now if zero_window else None,
                    message.source_turn_id,
                    now,
                    now,
                ),
            )
        connection.execute(
            "INSERT INTO input_batch_messages VALUES (?, ?)", (batch_id, message.message_id)
        )
        return batch_id

    def seal_due(self, connection: sqlite3.Connection, at: datetime) -> int:
        now = utc_text(at)
        return connection.execute(
            "UPDATE input_batches SET status = 'sealed', sealed_at_utc = ?, "
            "updated_at_utc = ? WHERE status = 'collecting' AND quiet_until_utc <= ?",
            (now, now, now),
        ).rowcount
