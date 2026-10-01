from __future__ import annotations

import sqlite3


class MemoryProvenanceRepository:
    def latest_digest(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str,
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT d.* FROM conversation_digests d JOIN memory_summary_batches b "
            "ON b.batch_id = d.batch_id "
            "WHERE b.community_id = ? AND b.character_id = ? AND b.conversation_id = ? "
            "ORDER BY d.covers_through_sequence DESC, d.created_at_utc DESC LIMIT 1",
            (community_id, character_id, conversation_id),
        ).fetchone()
