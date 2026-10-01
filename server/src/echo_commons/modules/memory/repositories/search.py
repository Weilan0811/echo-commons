from __future__ import annotations

import sqlite3
from datetime import datetime

from echo_commons.infrastructure.database.mapping import utc_text


class SearchRepository:
    def replace(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        conversation_id: str | None,
        source_kind: str,
        source_id: str,
        source_version: str,
        text: str,
        tokens: str,
        occurred_at: datetime | None,
        now: datetime,
    ) -> None:
        connection.execute(
            "INSERT INTO memory_search_documents (community_id, character_id, "
            "conversation_id, source_kind, source_id, source_version, "
            "occurred_at_utc, searchable, updated_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?) ON CONFLICT(character_id, "
            "source_kind, source_id) DO UPDATE SET "
            "source_version = excluded.source_version, occurred_at_utc = "
            "excluded.occurred_at_utc, searchable = excluded.searchable, "
            "updated_at_utc = excluded.updated_at_utc",
            (
                community_id,
                character_id,
                conversation_id,
                source_kind,
                source_id,
                source_version,
                utc_text(occurred_at) if occurred_at else None,
                int(bool(tokens)),
                utc_text(now),
            ),
        )
        row = connection.execute(
            "SELECT document_id FROM memory_search_documents WHERE character_id = ? "
            "AND source_kind = ? AND source_id = ?",
            (character_id, source_kind, source_id),
        ).fetchone()
        connection.execute("DELETE FROM memory_search_fts WHERE rowid = ?", (row[0],))
        connection.execute(
            "INSERT INTO memory_search_fts(rowid, tokenized_text, display_text) VALUES (?, ?, ?)",
            (row[0], tokens, text),
        )

    def clear(self, connection: sqlite3.Connection, community_id: str, character_id: str) -> None:
        connection.execute(
            "DELETE FROM memory_search_fts WHERE rowid IN (SELECT document_id FROM "
            "memory_search_documents WHERE community_id = ? AND character_id = ?)",
            (community_id, character_id),
        )
        connection.execute(
            "DELETE FROM memory_search_documents WHERE community_id = ? AND character_id = ?",
            (community_id, character_id),
        )

    def candidates(
        self, connection: sqlite3.Connection, community_id: str, character_id: str, match: str
    ) -> tuple[sqlite3.Row, ...]:
        return tuple(
            connection.execute(
                "SELECT d.*, bm25(memory_search_fts) AS rank FROM memory_search_fts "
                "JOIN memory_search_documents d ON d.document_id = memory_search_fts.rowid "
                "WHERE memory_search_fts MATCH ? AND d.community_id = ? AND "
                "d.character_id = ? AND d.searchable = 1 "
                "ORDER BY rank, d.document_id",
                (match, community_id, character_id),
            )
        )
