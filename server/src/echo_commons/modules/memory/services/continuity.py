from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.services.tokenization import tokenized_text
from echo_commons.shared.errors import ConflictError


class MemoryContinuity:
    def __init__(self, provenance):
        self.provenance = provenance

    def compress(self, connection, community_id, character_id, batch_id, content, now):
        batch = self.provenance.get_batch(connection, community_id, character_id, batch_id)
        self.provenance.batch_summaries(connection, batch)
        existing = self.provenance.digest_for_batch(connection, batch)
        if existing is not None:
            if content != existing["content"]:
                raise ConflictError("Summary batch already has a different character digest")
            return
        if any(
            self.provenance.continuity_consumed(connection, ref.segment_id) for ref in batch.sources
        ):
            raise ConflictError("Character digest sources overlap previous consumption")
        if content is None:
            raise ConflictError("reflection_digest_required")
        if not content.strip():
            raise ValueError("Character digest requires nonempty content")
        identity = self.provenance.add_digest(connection, batch, content, now)
        SearchRepository().replace(
            connection,
            community_id,
            character_id,
            None,
            "conversation_digest",
            identity,
            "1",
            content,
            tokenized_text(content),
            now,
            now,
        )
