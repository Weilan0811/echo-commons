from __future__ import annotations

import sqlite3
from datetime import timedelta
from uuid import uuid4

from echo_commons.modules.conversations.domain.input_batch import InputBatch
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.conversations.repositories.input_batches import InputBatchRepository
from echo_commons.shared.actors import ActorKind, ActorRef


class InputCollector:
    def __init__(self, batches: InputBatchRepository) -> None:
        self.batches = batches

    def collect(
        self, connection: sqlite3.Connection, message: Message, quiet_seconds: float
    ) -> str | None:
        if not isinstance(message.sender, ActorRef):
            raise ValueError("Input collection requires a player or character sender")
        if quiet_seconds < 0 or (message.sender.kind is ActorKind.CHARACTER and quiet_seconds != 0):
            raise ValueError(
                "Character input requires a zero window; player window must be nonnegative"
            )
        now = message.created_at_utc
        existing = self.batches.collecting(connection, message)
        if existing and not existing.accepts(message):
            self.batches.seal(connection, existing.input_batch_id, now)
            existing = None
        if existing:
            batch_id = existing.input_batch_id
            self.batches.extend(connection, batch_id, now + timedelta(seconds=quiet_seconds), now)
            if quiet_seconds == 0:
                self.batches.seal(connection, batch_id, now)
        else:
            batch_id = str(uuid4())
            self.batches.add(
                connection,
                InputBatch(
                    batch_id,
                    message.community_id,
                    message.conversation_id,
                    message.sender,
                    message.visibility,
                    message.audience,
                    "sealed" if quiet_seconds == 0 else "collecting",
                    now + timedelta(seconds=quiet_seconds),
                    now if quiet_seconds == 0 else None,
                    message.source_turn_id,
                    now,
                    now,
                ),
            )
        self.batches.link(connection, batch_id, message.message_id)
        return batch_id
