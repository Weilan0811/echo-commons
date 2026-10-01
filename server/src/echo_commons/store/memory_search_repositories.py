from __future__ import annotations

import sqlite3
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

import aiosqlite

from echo_commons.domain.memory import MemoryEntry
from echo_commons.domain.messages import Message
from echo_commons.store.database import Database
from echo_commons.store.repository_support import (
    get_connection,
    parse_time,
    require_write_connection,
    utc_text,
)

MAX_SEARCH_DISPLAY_CHARS = 512


class MemorySearchUnavailableError(RuntimeError):
    """The optional sparse index cannot be used on this SQLite build."""

    code = "memory_search_unavailable"


class SearchIndexWriter(Protocol):
    """Small write-side port used by authoritative repositories."""

    async def upsert_memory_entry(
        self,
        entry: MemoryEntry,
        *,
        connection: aiosqlite.Connection,
    ) -> None: ...

    async def upsert_message(
        self,
        message: Message,
        *,
        connection: aiosqlite.Connection,
    ) -> None: ...

    async def mark_memory_entry_unsearchable(
        self,
        entry: MemoryEntry,
        *,
        connection: aiosqlite.Connection,
    ) -> None: ...


@dataclass(frozen=True, slots=True)
class MemorySearchRow:
    """A bounded source row returned by either sparse or fallback search."""

    source_kind: str
    source_id: str
    source_ref: str
    memory_id: str | None
    memory_kind: str | None
    summary: str
    occurred_at_utc: datetime | None
    score: float
    retrieval_kind: str
    conversation_id: str | None = None
    content_version: str = ""


def _fts_error(exc: sqlite3.OperationalError) -> MemorySearchUnavailableError:
    message = str(exc).lower()
    if "fts5" in message or "no such module" in message or "no such table" in message:
        return MemorySearchUnavailableError("SQLite FTS5 is unavailable")
    raise exc


class MemorySearchRepository:
    """Store and query the derived document map and FTS5 rowset."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_conversation_character_ids(
        self,
        account_id: str,
        conversation_id: str,
        *,
        connection: aiosqlite.Connection,
    ) -> tuple[str, ...]:
        """Read character scopes for one conversation from the Store layer."""

        cursor = await connection.execute(
            """SELECT character_id FROM conversation_participants
               WHERE account_id = ? AND conversation_id = ?
               ORDER BY left_at_utc IS NULL DESC, joined_at_utc DESC, character_id""",
            (account_id, conversation_id),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(row["character_id"] for row in rows)

    async def list_memory_entry_rows(
        self,
        account_id: str,
        character_id: str,
        *,
        connection: aiosqlite.Connection,
    ) -> tuple[aiosqlite.Row, ...]:
        """Read authoritative memory rows for projection rebuilds."""

        cursor = await connection.execute(
            """SELECT * FROM memory_entries
               WHERE account_id = ? AND character_id = ?""",
            (account_id, character_id),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(rows)

    async def list_message_rows_for_character(
        self,
        account_id: str,
        character_id: str,
        *,
        connection: aiosqlite.Connection,
    ) -> tuple[aiosqlite.Row, ...]:
        """Read searchable player/character messages for one character scope."""

        cursor = await connection.execute(
            """SELECT DISTINCT m.* FROM messages AS m
               JOIN conversation_participants AS p
                 ON p.account_id = m.account_id AND p.conversation_id = m.conversation_id
               WHERE m.account_id = ? AND p.character_id = ?
                 AND m.sender_type IN ('player', 'character')
               ORDER BY m.message_sequence ASC""",
            (account_id, character_id),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(rows)

    async def _document_id(
        self,
        *,
        account_id: str,
        character_id: str,
        source_kind: str,
        source_id: str,
        connection: aiosqlite.Connection,
    ) -> int | None:
        cursor = await connection.execute(
            """SELECT document_id FROM memory_search_documents
               WHERE account_id = ? AND character_id = ?
                 AND source_kind = ? AND source_id = ?""",
            (account_id, character_id, source_kind, source_id),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return int(row["document_id"]) if row else None

    async def upsert_document(
        self,
        *,
        account_id: str,
        character_id: str,
        conversation_id: str | None,
        source_kind: str,
        source_id: str,
        source_version: str,
        occurred_at_utc: datetime | None,
        tokenized_text: str,
        display_text: str,
        searchable: bool = True,
        updated_at_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> int:
        conn = require_write_connection(connection)
        try:
            document_id = await self._document_id(
                account_id=account_id,
                character_id=character_id,
                source_kind=source_kind,
                source_id=source_id,
                connection=conn,
            )
            if document_id is None:
                cursor = await conn.execute(
                    """INSERT INTO memory_search_documents(
                        account_id, character_id, conversation_id, source_kind, source_id,
                        source_version, occurred_at_utc, searchable, updated_at_utc
                    ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
                    (
                        account_id,
                        character_id,
                        conversation_id,
                        source_kind,
                        source_id,
                        source_version,
                        utc_text(occurred_at_utc) if occurred_at_utc else None,
                        int(searchable),
                        utc_text(updated_at_utc),
                    ),
                )
                document_id = int(cursor.lastrowid)
            else:
                await conn.execute(
                    """UPDATE memory_search_documents
                       SET conversation_id = ?, source_version = ?, occurred_at_utc = ?,
                           searchable = ?, updated_at_utc = ?
                       WHERE document_id = ?""",
                    (
                        conversation_id,
                        source_version,
                        utc_text(occurred_at_utc) if occurred_at_utc else None,
                        int(searchable),
                        utc_text(updated_at_utc),
                        document_id,
                    ),
                )
                await conn.execute(
                    "DELETE FROM memory_search_fts WHERE rowid = ?",
                    (document_id,),
                )
            if searchable and tokenized_text:
                await conn.execute(
                    "INSERT INTO memory_search_fts(rowid, tokenized_text, display_text) "
                    "VALUES (?, ?, ?)",
                    (document_id, tokenized_text, display_text),
                )
            return document_id
        except sqlite3.OperationalError as exc:
            raise _fts_error(exc) from exc

    async def mark_unsearchable(
        self,
        *,
        account_id: str,
        character_id: str,
        source_kind: str,
        source_id: str,
        updated_at_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        conn = require_write_connection(connection)
        try:
            document_id = await self._document_id(
                account_id=account_id,
                character_id=character_id,
                source_kind=source_kind,
                source_id=source_id,
                connection=conn,
            )
            if document_id is None:
                return
            await conn.execute(
                "UPDATE memory_search_documents SET searchable = 0, updated_at_utc = ? "
                "WHERE document_id = ?",
                (utc_text(updated_at_utc), document_id),
            )
            await conn.execute("DELETE FROM memory_search_fts WHERE rowid = ?", (document_id,))
        except sqlite3.OperationalError as exc:
            raise _fts_error(exc) from exc

    async def search(
        self,
        *,
        account_id: str,
        character_id: str,
        match_query: str,
        now_utc: datetime,
        limit: int,
        conversation_id: str | None = None,
        frozen_conversation_id: str | None = None,
        frozen_max_sequence: int | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[MemorySearchRow, ...]:
        conn = get_connection(self.database, connection)
        now = utc_text(now_utc)
        conversation_clause = ""
        parameters: list[object] = [match_query, account_id, character_id, now]
        if conversation_id is not None:
            conversation_clause = " AND (d.source_kind = 'memory_entry' OR d.conversation_id = ?)"
            parameters.append(conversation_id)
        if frozen_conversation_id is not None:
            conversation_clause += (
                " AND (d.source_kind='memory_entry' OR "
                "m.conversation_id<>? OR m.message_sequence<=?)"
            )
            parameters.extend((frozen_conversation_id, frozen_max_sequence))
        parameters.append(limit)
        sql = f"""SELECT d.source_kind, d.source_id, d.conversation_id,
                          SUBSTR(COALESCE(me.content,m.text),1,512) AS display_text,
                          COALESCE(me.content_version,m.message_id) AS content_version,
                          bm25(memory_search_fts) AS rank,
                          me.memory_kind AS memory_kind, me.source_ref AS memory_source_ref,
                          me.occurred_at_utc AS memory_occurred_at,
                          me.recorded_at_utc AS memory_recorded_at,
                          m.message_id AS message_source_id,
                          m.server_timestamp_utc AS message_occurred_at
                   FROM memory_search_fts AS f
                   JOIN memory_search_documents AS d ON d.document_id = f.rowid
                   LEFT JOIN memory_entries AS me
                     ON d.source_kind = 'memory_entry'
                    AND me.account_id = d.account_id
                    AND me.character_id = d.character_id
                    AND me.memory_id = d.source_id
                   LEFT JOIN messages AS m
                     ON d.source_kind = 'message'
                    AND m.account_id = d.account_id
                    AND m.message_id = d.source_id
                   WHERE memory_search_fts MATCH ?
                     AND d.account_id = ? AND d.character_id = ? AND d.searchable = 1
                     AND (
                         (d.source_kind = 'memory_entry'
                          AND me.memory_id IS NOT NULL AND d.source_version=me.content_version
                          AND me.visibility IN ('resident', 'recallable')
                          AND me.invalidated_at_utc IS NULL
                          AND (me.expires_at_utc IS NULL OR me.expires_at_utc > ?))
                         OR
                         (d.source_kind = 'message'
                          AND m.message_id IS NOT NULL
                          AND m.sender_type IN ('player', 'character')
                          AND EXISTS (
                              SELECT 1 FROM conversation_participants AS p
                              WHERE p.account_id = m.account_id
                                AND p.conversation_id = m.conversation_id
                                AND p.character_id = d.character_id
                          ))
                     )
                     {conversation_clause}
                   ORDER BY rank ASC,
                            COALESCE(me.occurred_at_utc, me.recorded_at_utc,
                                     m.server_timestamp_utc) DESC,
                            d.source_id ASC
                   LIMIT ?"""
        try:
            cursor = await conn.execute(sql, tuple(parameters))
        except sqlite3.OperationalError as exc:
            raise _fts_error(exc) from exc
        try:
            rows = await cursor.fetchall()
        except sqlite3.OperationalError as exc:
            raise _fts_error(exc) from exc
        finally:
            await cursor.close()
        return tuple(
            MemorySearchRow(
                source_kind=row["source_kind"],
                source_id=row["source_id"],
                source_ref=(
                    row["memory_source_ref"]
                    if row["source_kind"] == "memory_entry"
                    else f"message:{row['message_source_id']}"
                ),
                memory_id=row["source_id"] if row["source_kind"] == "memory_entry" else None,
                memory_kind=row["memory_kind"],
                summary=row["display_text"],
                content_version=row["content_version"],
                occurred_at_utc=_parse_time(
                    row["memory_occurred_at"]
                    or row["memory_recorded_at"]
                    or row["message_occurred_at"]
                ),
                score=max(0.0, -float(row["rank"] or 0.0)),
                retrieval_kind="fts5",
                conversation_id=row["conversation_id"],
            )
            for row in rows
        )

    async def structured_search(
        self,
        *,
        account_id: str,
        character_id: str,
        terms: tuple[str, ...],
        now_utc: datetime,
        limit: int,
        conversation_id: str | None = None,
        frozen_conversation_id: str | None = None,
        frozen_max_sequence: int | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[MemorySearchRow, ...]:
        """Conservative SQL fallback used when FTS5 is unavailable."""

        conn = get_connection(self.database, connection)
        if not terms:
            return ()
        clauses = " OR ".join("LOWER(me.content) LIKE ?" for _ in terms)
        parameters: list[object] = [f"%{term.lower()}%" for term in terms]
        parameters.extend([account_id, character_id, utc_text(now_utc)])
        cursor = await conn.execute(
            f"""SELECT me.memory_id, me.memory_kind, me.content, me.source_ref, me.content_version,
                       me.occurred_at_utc, me.recorded_at_utc
                FROM memory_entries AS me
                WHERE ({clauses})
                  AND me.account_id = ? AND me.character_id = ?
                  AND me.visibility IN ('resident', 'recallable')
                  AND me.invalidated_at_utc IS NULL
                  AND (me.expires_at_utc IS NULL OR me.expires_at_utc > ?)
                ORDER BY me.salience DESC, me.recorded_at_utc DESC, me.memory_id
                LIMIT ?""",
            (*parameters, limit),
        )
        try:
            memory_rows = await cursor.fetchall()
        finally:
            await cursor.close()
        memory_results = tuple(
            MemorySearchRow(
                source_kind="memory_entry",
                source_id=row["memory_id"],
                source_ref=row["source_ref"],
                memory_id=row["memory_id"],
                memory_kind=row["memory_kind"],
                summary=row["content"][:MAX_SEARCH_DISPLAY_CHARS],
                content_version=row["content_version"],
                occurred_at_utc=_parse_time(row["occurred_at_utc"] or row["recorded_at_utc"]),
                score=0.0,
                retrieval_kind="structured",
            )
            for row in memory_rows
        )
        message_clauses = " OR ".join("LOWER(m.text) LIKE ?" for _ in terms)
        message_parameters: list[object] = [f"%{term.lower()}%" for term in terms]
        message_parameters.extend([account_id, character_id])
        conversation_clause = ""
        if conversation_id is not None:
            conversation_clause = " AND m.conversation_id = ?"
            message_parameters.append(conversation_id)
        if frozen_conversation_id is not None:
            conversation_clause += " AND (m.conversation_id<>? OR m.message_sequence<=?)"
            message_parameters.extend((frozen_conversation_id, frozen_max_sequence))
        message_cursor = await conn.execute(
            f"""SELECT m.message_id, m.conversation_id, m.text, m.server_timestamp_utc
                FROM messages AS m
                WHERE ({message_clauses})
                  AND m.account_id = ?
                  AND m.sender_type IN ('player', 'character')
                  AND EXISTS (
                      SELECT 1 FROM conversation_participants AS p
                      WHERE p.account_id = m.account_id
                        AND p.conversation_id = m.conversation_id
                        AND p.character_id = ?
                  )
                  {conversation_clause}
                ORDER BY m.server_timestamp_utc DESC, m.message_id
                LIMIT ?""",
            (*message_parameters, limit),
        )
        try:
            message_rows = await message_cursor.fetchall()
        finally:
            await message_cursor.close()
        message_results = tuple(
            MemorySearchRow(
                source_kind="message",
                source_id=row["message_id"],
                source_ref=f"message:{row['message_id']}",
                memory_id=None,
                memory_kind=None,
                summary=row["text"][:MAX_SEARCH_DISPLAY_CHARS],
                content_version=row["message_id"],
                occurred_at_utc=_parse_time(row["server_timestamp_utc"]),
                score=0.0,
                retrieval_kind="structured",
                conversation_id=row["conversation_id"],
            )
            for row in message_rows
        )
        combined = [*memory_results, *message_results]
        combined.sort(
            key=lambda row: (
                row.occurred_at_utc is not None,
                row.occurred_at_utc,
                row.source_id,
            ),
            reverse=True,
        )
        return tuple(combined[:limit])

    async def rebuild_scope(
        self,
        account_id: str,
        character_id: str,
        *,
        connection: aiosqlite.Connection,
    ) -> None:
        """Reset one derived scope while preserving source document identities."""

        cursor = await connection.execute(
            "SELECT document_id FROM memory_search_documents "
            "WHERE account_id = ? AND character_id = ?",
            (account_id, character_id),
        )
        try:
            document_ids = tuple(int(row["document_id"]) for row in await cursor.fetchall())
        finally:
            await cursor.close()
        try:
            for document_id in document_ids:
                await connection.execute(
                    "DELETE FROM memory_search_fts WHERE rowid = ?", (document_id,)
                )
            # Keep document_id stable so a future vector or graph projection
            # can retain its row identity across sparse-index rebuilds.
            await connection.execute(
                "UPDATE memory_search_documents SET searchable = 0 "
                "WHERE account_id = ? AND character_id = ?",
                (account_id, character_id),
            )
        except sqlite3.OperationalError as exc:
            raise _fts_error(exc) from exc


def _parse_time(value: object) -> datetime | None:
    if not isinstance(value, str):
        return None
    return parse_time(value)


__all__ = [
    "MAX_SEARCH_DISPLAY_CHARS",
    "MemorySearchRepository",
    "MemorySearchRow",
    "MemorySearchUnavailableError",
    "SearchIndexWriter",
]
