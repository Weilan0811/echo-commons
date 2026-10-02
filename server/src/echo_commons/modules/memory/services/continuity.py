import sqlite3
from datetime import datetime

from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository
from echo_commons.shared.errors import ConflictError


class MemoryContinuity:
    def __init__(self, provenance: MemoryProvenanceRepository) -> None:
        self.provenance = provenance

    def compress(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        batch_id: str,
        content: str | None,
        covers_through_sequence: int,
        now: datetime,
    ) -> None:
        batch = self.provenance.get_batch(connection, community_id, character_id, batch_id)
        summaries = self.provenance.batch_summaries(connection, batch)
        if covers_through_sequence != summaries[-1]["last_message_sequence"]:
            raise ConflictError("Conversation digest coverage disagrees with its summary sources")
        existing = self.provenance.digest_for_batch(connection, batch)
        if existing is not None:
            if content != existing["content"]:
                raise ConflictError("Summary batch already has a different conversation digest")
            return
        latest = self.provenance.latest_digest(
            connection, community_id, character_id, batch.conversation_id
        )
        if (latest["digest_id"] if latest else None) != batch.previous_digest_id:
            raise ConflictError("Conversation digest source has been superseded")
        if latest and summaries[0]["first_message_sequence"] <= latest["covers_through_sequence"]:
            raise ConflictError("Conversation digest sources overlap the previous digest")
        if content is None:
            raise ConflictError("reflection_digest_required")
        if not content.strip():
            raise ValueError("Conversation digest requires nonempty content")
        self.provenance.add_digest(connection, batch, content, covers_through_sequence, now)
