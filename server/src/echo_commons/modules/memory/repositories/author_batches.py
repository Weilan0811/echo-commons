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
                "SELECT c.*,m.blueprint_version,m.question,m.created_at_utc FROM "
                "memory_author_chunks c "
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
            (row["source_id"], row["source_version"])
            for row in connection.execute(
                "SELECT source_id,source_version FROM "
                "memory_organization_coverage WHERE character_id=? "
                "AND stage='cognitions' AND source_kind='author_chunk'",
                (character_id,),
            )
        }
        selected, size = [], 0
        for row in rows:
            if (row["chunk_id"], row["blueprint_version"]) in consumed:
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
            json.dumps(
                [(row["chunk_id"], row["blueprint_version"]) for row in selected],
                ensure_ascii=False,
                separators=(",", ":"),
            ),
            tuple(row["chunk_id"] for row in selected),
        )
        existing = connection.execute(
            "SELECT batch_id FROM memory_author_batches WHERE community_id=? AND character_id=? "
            "AND source_version=? AND outcome IS NULL ORDER BY created_at_utc LIMIT 1",
            (community_id, character_id, batch.source_version),
        ).fetchone()
        if existing:
            return self.get(connection, community_id, character_id, existing[0])
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
        expected = dict(json.loads(batch.source_version))
        if any(
            identity not in rows or rows[identity]["blueprint_version"] != expected[identity]
            for identity in batch.chunk_ids
        ):
            raise ConflictError("Author batch source is unavailable")
        return tuple(rows[identity] for identity in batch.chunk_ids)
