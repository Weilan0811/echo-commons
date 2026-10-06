import sqlite3
from datetime import datetime

import numpy as np

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.domain.policy import VectorPolicy


class VectorRepository:
    def pending(
        self, connection: sqlite3.Connection, identity: str, policy: VectorPolicy
    ) -> tuple[dict, ...]:
        rows = connection.execute(
            "SELECT d.*,f.display_text FROM memory_search_documents d "
            "JOIN memory_search_fts f ON f.rowid=d.document_id "
            "LEFT JOIN memory_vectors v ON v.document_id=d.document_id "
            "WHERE d.searchable=1 AND (v.document_id IS NULL "
            "OR v.source_version!=d.source_version OR v.model_identity!=?) "
            "AND NOT EXISTS (SELECT 1 FROM memory_vector_failures x WHERE "
            "x.document_id=d.document_id AND x.source_version=d.source_version "
            "AND x.model_identity=?) ORDER BY d.document_id",
            (identity, identity),
        )
        chosen, chars = [], 0
        for row in rows:
            size = len(row["display_text"])
            if size > policy.batch_max_chars:
                return (dict(row),) if not chosen else tuple(chosen)
            if chars + size > policy.batch_max_chars or len(chosen) == policy.batch_size:
                break
            chars += size
            chosen.append(dict(row))
        return tuple(chosen)

    @staticmethod
    def current(connection: sqlite3.Connection, row: dict) -> bool:
        actual = connection.execute(
            "SELECT character_id,source_kind,source_id,source_version "
            "FROM memory_search_documents WHERE document_id=?",
            (row["document_id"],),
        ).fetchone()
        return actual is not None and tuple(actual) == tuple(
            row[key] for key in ("character_id", "source_kind", "source_id", "source_version")
        )

    def save(
        self,
        connection: sqlite3.Connection,
        row: dict,
        vector: np.ndarray,
        identity: str,
        now: datetime,
    ) -> None:
        if not self.current(connection, row):
            return
        connection.execute(
            "INSERT INTO memory_vectors VALUES (?,?,?,?,?,?) "
            "ON CONFLICT(document_id) DO UPDATE SET source_version=excluded.source_version, "
            "model_identity=excluded.model_identity, dimensions=excluded.dimensions, "
            "vector=excluded.vector, updated_at_utc=excluded.updated_at_utc",
            (
                row["document_id"],
                row["source_version"],
                identity,
                len(vector),
                vector.tobytes(),
                utc_text(now),
            ),
        )

    def failure(
        self,
        connection: sqlite3.Connection,
        row: dict,
        identity: str,
        code: str,
        attempts: int,
        now: datetime,
    ) -> None:
        if self.current(connection, row):
            connection.execute(
                "INSERT OR REPLACE INTO memory_vector_failures VALUES (?,?,?,?,?,?)",
                (
                    row["document_id"],
                    row["source_version"],
                    identity,
                    code,
                    attempts,
                    utc_text(now),
                ),
            )

    def candidates(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        identity: str,
        dimensions: int,
    ) -> tuple[sqlite3.Row, ...]:
        return tuple(
            connection.execute(
                "SELECT d.source_kind,d.source_id,d.source_version,v.vector FROM memory_vectors v "
                "JOIN memory_search_documents d ON d.document_id=v.document_id "
                "WHERE d.community_id=? AND d.character_id=? AND d.searchable=1 "
                "AND v.model_identity=? AND v.dimensions=? AND v.source_version=d.source_version",
                (community_id, character_id, identity, dimensions),
            )
        )
