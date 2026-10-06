import json
from datetime import datetime
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.domain.batches import AuthorBatch
from echo_commons.shared.errors import ConflictError, NotFoundError


class AuthorBatchRepository:
    def chunks(self, connection, character_id):
        return tuple(
            connection.execute(
                "SELECT c.*,m.blueprint_version,m.question FROM memory_author_chunks c "
                "JOIN memory_author_materials m USING(material_id) WHERE m.character_id=? "
                "ORDER BY m.material_kind,m.position,c.position",
                (character_id,),
            )
        )

    def freeze(
        self, connection, community_id, character_id, now: datetime, *, max_count, max_chars
    ):
        rows = self.chunks(connection, character_id)
        consumed = {
            chunk
            for batch in connection.execute(
                "SELECT chunk_ids_json FROM memory_author_batches WHERE character_id=? "
                "AND outcome IS NOT NULL",
                (character_id,),
            )
            for chunk in json.loads(batch[0])
        }
        selected, size = [], 0
        for row in rows:
            if row["chunk_id"] in consumed:
                continue
            chars = len(row["content"]) + len(row["question"] or "")
            if len(selected) >= max_count or size + chars > max_chars:
                if not selected:
                    raise ConflictError("Author material exceeds reflection input budget")
                break
            selected.append(row)
            size += chars
        if not selected:
            return None
        batch = AuthorBatch(
            str(uuid4()),
            community_id,
            character_id,
            selected[0]["blueprint_version"],
            tuple(row["chunk_id"] for row in selected),
        )
        connection.execute(
            "INSERT INTO memory_author_batches VALUES (?,?,?,?,?,NULL,?,NULL)",
            (
                batch.batch_id,
                community_id,
                character_id,
                batch.source_version,
                json.dumps(batch.chunk_ids),
                utc_text(now),
            ),
        )
        return batch

    def get(self, connection, community_id, character_id, batch_id):
        row = connection.execute(
            "SELECT * FROM memory_author_batches WHERE community_id=? AND character_id=? "
            "AND batch_id=?",
            (community_id, character_id, batch_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Author batch does not exist")
        return AuthorBatch(
            batch_id,
            community_id,
            character_id,
            row["source_version"],
            tuple(json.loads(row["chunk_ids_json"])),
        )

    def materials(self, connection, batch):
        rows = {row["chunk_id"]: row for row in self.chunks(connection, batch.character_id)}
        if any(
            identity not in rows or rows[identity]["blueprint_version"] != batch.source_version
            for identity in batch.chunk_ids
        ):
            raise ConflictError("Author batch source is unavailable")
        return tuple(rows[identity] for identity in batch.chunk_ids)
