"""Repositories for long-term memory pages, private records, and graph indexes.

The repositories keep memory persistence deliberately boring: the page tables
are authoritative, while graph rows are rebuildable projections over those
pages.  Every write requires a Runtime-owned SQLite transaction.
"""

from __future__ import annotations

import hashlib
import json
from contextlib import suppress
from datetime import datetime
from uuid import UUID

import aiosqlite

from echo_server.domain.errors import DomainInvariantError, require_non_empty, require_sequence
from echo_server.domain.memory import (
    DiaryEntry,
    MemoryEdge,
    MemoryEntity,
    MemoryEntityAlias,
    MemoryEntry,
    MemoryEntryEntityLink,
    MemorySegment,
    MemorySegmentStatus,
    MemoryView,
    MemoryViewKind,
    Thought,
)
from echo_server.store.database import Database
from echo_server.store.memory_search_repositories import (
    MemorySearchUnavailableError,
    SearchIndexWriter,
)
from echo_server.store.repository_support import (
    as_json,
    get_connection,
    parse_time,
    require_write_connection,
    utc_text,
)


def _required_uuid(value: object, field_name: str) -> UUID:
    if not isinstance(value, str):
        raise DomainInvariantError(f"{field_name} must contain a UUID")
    try:
        return UUID(value)
    except ValueError as exc:
        raise DomainInvariantError(f"{field_name} must contain a UUID") from exc


def _required_time(value: object, field_name: str) -> datetime:
    try:
        parsed = parse_time(value if isinstance(value, str) else None)
    except ValueError as exc:
        raise DomainInvariantError(f"{field_name} must contain a timestamp") from exc
    if parsed is None:
        raise DomainInvariantError(f"{field_name} must contain a timestamp")
    return parsed


def _optional_time(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _required_time(value, field_name)


def _check_rowcount(rowcount: int, entity: str) -> None:
    if rowcount != 1:
        raise RuntimeError(f"{entity} persistence precondition failed")


def _segment_from_row(row: aiosqlite.Row) -> MemorySegment:
    return MemorySegment(
        segment_id=_required_uuid(row["segment_id"], "segment_id"),
        account_id=row["account_id"],
        conversation_id=row["conversation_id"],
        character_id=row["character_id"],
        first_message_sequence=int(row["first_message_sequence"]),
        last_message_sequence=int(row["last_message_sequence"]),
        status=MemorySegmentStatus(row["status"]),
        summary_text=row["summary_text"],
        summary_version=row["summary_version"],
        source_version=row["source_version"],
        sealed_at_utc=_required_time(row["sealed_at_utc"], "sealed_at_utc"),
        ingested_at_utc=_optional_time(row["ingested_at_utc"], "ingested_at_utc"),
        created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
        updated_at_utc=_required_time(row["updated_at_utc"], "updated_at_utc"),
    )


def _entry_from_row(row: aiosqlite.Row) -> MemoryEntry:
    return MemoryEntry(
        account_id=row["account_id"],
        character_id=row["character_id"],
        memory_id=row["memory_id"],
        memory_kind=row["memory_kind"],
        content=row["content"],
        confidence=float(row["confidence"]),
        salience=float(row["salience"]),
        source_kind=row["source_kind"],
        source_ref=row["source_ref"],
        subject_kind=row["subject_kind"],
        subject_id=row["subject_id"],
        visibility=row["visibility"],
        content_version=row["content_version"],
        occurred_at_utc=_optional_time(row["occurred_at_utc"], "occurred_at_utc"),
        recorded_at_utc=_required_time(row["recorded_at_utc"], "recorded_at_utc"),
        expires_at_utc=_optional_time(row["expires_at_utc"], "expires_at_utc"),
        invalidated_at_utc=_optional_time(row["invalidated_at_utc"], "invalidated_at_utc"),
    )


def _diary_from_row(row: aiosqlite.Row) -> DiaryEntry:
    return DiaryEntry(
        diary_id=_required_uuid(row["diary_id"], "diary_id"),
        account_id=row["account_id"],
        character_id=row["character_id"],
        game_day=row["game_day"],
        content=row["content"],
        source_window_kind=row["source_window_kind"],
        source_window_ref=row["source_window_ref"],
        content_version=row["content_version"],
        created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
    )


def _thought_from_row(row: aiosqlite.Row) -> Thought:
    return Thought(
        thought_id=_required_uuid(row["thought_id"], "thought_id"),
        result_id=_required_uuid(row["result_id"], "result_id"),
        conversation_id=row["conversation_id"],
        segment_id=UUID(row["segment_id"]) if row["segment_id"] else None,
        account_id=row["account_id"],
        character_id=row["character_id"],
        game_day=row["game_day"],
        content=row["content"],
        created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
    )


def _entity_from_row(row: aiosqlite.Row) -> MemoryEntity:
    return MemoryEntity(
        account_id=row["account_id"],
        character_id=row["character_id"],
        entity_id=row["entity_id"],
        entity_kind=row["entity_kind"],
        canonical_name=row["canonical_name"],
        created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
        updated_at_utc=_required_time(row["updated_at_utc"], "updated_at_utc"),
        invalidated_at_utc=_optional_time(row["invalidated_at_utc"], "invalidated_at_utc"),
    )


def _edge_from_row(row: aiosqlite.Row) -> MemoryEdge:
    return MemoryEdge(
        edge_id=_required_uuid(row["edge_id"], "edge_id"),
        account_id=row["account_id"],
        character_id=row["character_id"],
        from_entity_id=row["from_entity_id"],
        to_entity_id=row["to_entity_id"],
        edge_kind=row["edge_kind"],
        confidence=float(row["confidence"]),
        source_memory_id=row["source_memory_id"],
        created_at_utc=_required_time(row["created_at_utc"], "created_at_utc"),
        invalidated_at_utc=_optional_time(row["invalidated_at_utc"], "invalidated_at_utc"),
    )


class MemorySegmentRepository:
    """Persist sealed conversation windows used by later ingestion workflows."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(
        self,
        segment_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> MemorySegment | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM memory_segments WHERE segment_id = ?",
            (str(segment_id),),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return _segment_from_row(row) if row else None

    async def list_for_scope(
        self,
        account_id: str,
        conversation_id: str,
        character_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[MemorySegment, ...]:
        scope = tuple(
            require_non_empty(value, field)
            for value, field in (
                (account_id, "account_id"),
                (conversation_id, "conversation_id"),
                (character_id, "character_id"),
            )
        )
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            """SELECT * FROM memory_segments
               WHERE account_id = ? AND conversation_id = ? AND character_id = ?
               ORDER BY first_message_sequence, segment_id""",
            scope,
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(_segment_from_row(row) for row in rows)

    async def list_for_character(
        self,
        account_id: str,
        character_id: str,
        *,
        status: MemorySegmentStatus | str | None = None,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[MemorySegment, ...]:
        """List source windows across conversations for phase organization."""

        account = require_non_empty(account_id, "account_id")
        character = require_non_empty(character_id, "character_id")
        conn = get_connection(self.database, connection)
        parameters: list[object] = [account, character]
        status_clause = ""
        if status is not None:
            status_clause = " AND status = ?"
            parameters.append(MemorySegmentStatus(status).value)
        cursor = await conn.execute(
            "SELECT * FROM memory_segments WHERE account_id = ? AND character_id = ?"
            + status_clause
            + " ORDER BY sealed_at_utc, segment_id",
            tuple(parameters),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(_segment_from_row(row) for row in rows)

    async def create(
        self,
        segment: MemorySegment,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> MemorySegment:
        conn = require_write_connection(connection)
        await conn.execute(
            """INSERT INTO memory_segments(
                segment_id, account_id, conversation_id, character_id,
                first_message_sequence, last_message_sequence, status, summary_text,
                source_version, sealed_at_utc, ingested_at_utc, created_at_utc, updated_at_utc,
                summary_version
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(segment.segment_id),
                segment.account_id,
                segment.conversation_id,
                segment.character_id,
                segment.first_message_sequence,
                segment.last_message_sequence,
                segment.status.value,
                segment.summary_text,
                segment.source_version,
                utc_text(segment.sealed_at_utc),
                utc_text(segment.ingested_at_utc) if segment.ingested_at_utc else None,
                utc_text(segment.created_at_utc),
                utc_text(segment.updated_at_utc),
                segment.summary_version,
            ),
        )
        return segment

    async def ensure(
        self,
        segment: MemorySegment,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> MemorySegment:
        """Create a source window once without rewriting its boundaries."""

        existing = await self.get(segment.segment_id, connection=connection)
        if existing is None:
            return await self.create(segment, connection=connection)
        immutable_fields = (
            "account_id",
            "conversation_id",
            "character_id",
            "first_message_sequence",
            "last_message_sequence",
            "summary_text",
            "source_version",
            "sealed_at_utc",
        )
        if any(getattr(existing, field) != getattr(segment, field) for field in immutable_fields):
            raise DomainInvariantError(
                "memory segment identity already contains different boundaries"
            )
        return existing

    async def mark_ingested(
        self,
        segment_id: UUID,
        *,
        ingested_at_utc: datetime,
        updated_at_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> MemorySegment:
        conn = require_write_connection(connection)
        ingested = utc_text(ingested_at_utc)
        updated = utc_text(updated_at_utc)
        cursor = await conn.execute(
            """UPDATE memory_segments
               SET status = 'ingested', ingested_at_utc = ?, updated_at_utc = ?
               WHERE segment_id = ? AND status = 'sealed'""",
            (ingested, updated, str(segment_id)),
        )
        _check_rowcount(cursor.rowcount, "memory segment ingestion")
        segment = await self.get(segment_id, connection=conn)
        if segment is None:
            raise RuntimeError("memory segment disappeared after ingestion")
        return segment

    async def update_summary(
        self,
        segment_id: UUID,
        *,
        summary_text: str,
        expected_source_version: str,
        updated_at_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> MemorySegment:
        """Persist a reviewed summary while the source segment is still sealed."""

        conn = require_write_connection(connection)
        if not summary_text.strip():
            raise DomainInvariantError("memory segment summary must contain text")
        cursor = await conn.execute(
            "UPDATE memory_segments SET summary_text = ?, summary_version = ?, updated_at_utc = ? "
            "WHERE segment_id = ? AND status = 'sealed' AND source_version = ?",
            (
                summary_text.strip(),
                hashlib.sha256(summary_text.strip().encode()).hexdigest(),
                utc_text(updated_at_utc),
                str(segment_id),
                expected_source_version,
            ),
        )
        _check_rowcount(cursor.rowcount, "memory segment summary")
        segment = await self.get(segment_id, connection=conn)
        if segment is None:
            raise RuntimeError("memory segment disappeared after summary update")
        return segment


class MemoryEntryRepository:
    """Authoritative long-term memory pages and resident projection reads."""

    def __init__(
        self,
        database: Database,
        *,
        search_index: SearchIndexWriter | None = None,
    ) -> None:
        self.database = database
        self.search_index = search_index

    async def get(
        self,
        account_id: str,
        character_id: str,
        memory_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryEntry | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            """SELECT * FROM memory_entries
               WHERE account_id = ? AND character_id = ? AND memory_id = ?""",
            (
                require_non_empty(account_id, "account_id"),
                require_non_empty(character_id, "character_id"),
                require_non_empty(memory_id, "memory_id"),
            ),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return _entry_from_row(row) if row else None

    async def list_for_scope(
        self,
        account_id: str,
        character_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[MemoryEntry, ...]:
        scope = (
            require_non_empty(account_id, "account_id"),
            require_non_empty(character_id, "character_id"),
        )
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            """SELECT * FROM memory_entries
               WHERE account_id = ? AND character_id = ?
               ORDER BY recorded_at_utc, memory_id""",
            scope,
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(_entry_from_row(row) for row in rows)

    async def list_resident(
        self,
        account_id: str,
        character_id: str,
        *,
        now_utc: datetime,
        limit: int = 32,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[tuple[MemoryEntry, ...], str]:
        scope = (
            require_non_empty(account_id, "account_id"),
            require_non_empty(character_id, "character_id"),
        )
        bounded_limit = require_sequence(limit, "limit", minimum=1)
        now = utc_text(now_utc)
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            """SELECT * FROM memory_entries
               WHERE account_id = ? AND character_id = ?
                 AND visibility = 'resident'
                 AND invalidated_at_utc IS NULL
                 AND (expires_at_utc IS NULL OR expires_at_utc > ?)
               ORDER BY salience DESC, recorded_at_utc DESC, memory_id
               LIMIT ?""",
            (*scope, now, bounded_limit),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        entries = tuple(_entry_from_row(row) for row in rows)
        version_cursor = await conn.execute(
            """SELECT COUNT(*) AS count, MAX(recorded_at_utc) AS latest,
                      group_concat(memory_id || ':' || content_version, '|') AS fingerprint
               FROM (
                   SELECT memory_id, content_version, recorded_at_utc
                   FROM memory_entries
                   WHERE account_id = ? AND character_id = ?
                     AND visibility = 'resident'
                     AND invalidated_at_utc IS NULL
                     AND (expires_at_utc IS NULL OR expires_at_utc > ?)
                   ORDER BY memory_id
               )""",
            (*scope, now),
        )
        try:
            version_row = await version_cursor.fetchone()
        finally:
            await version_cursor.close()
        count = int(version_row["count"] if version_row else 0)
        latest = version_row["latest"] if version_row else None
        fingerprint = version_row["fingerprint"] if version_row else None
        if not count:
            return entries, "empty"
        version_hash = hashlib.sha256(fingerprint.encode()).hexdigest()[:16]
        return entries, f"{count}:{latest}:{version_hash}"

    async def insert(
        self,
        entry: MemoryEntry,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryEntry:
        conn = require_write_connection(connection)
        await conn.execute(
            """INSERT INTO memory_entries(
                account_id, character_id, memory_id, memory_kind, content,
                confidence, salience, source_kind, source_ref, subject_kind, subject_id,
                visibility, content_version, occurred_at_utc, recorded_at_utc,
                expires_at_utc, invalidated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                entry.account_id,
                entry.character_id,
                entry.memory_id,
                entry.memory_kind.value,
                entry.content,
                entry.confidence,
                entry.salience,
                entry.source_kind,
                entry.source_ref,
                entry.subject_kind,
                entry.subject_id,
                entry.visibility.value,
                entry.content_version,
                utc_text(entry.occurred_at_utc) if entry.occurred_at_utc else None,
                utc_text(entry.recorded_at_utc),
                utc_text(entry.expires_at_utc) if entry.expires_at_utc else None,
                utc_text(entry.invalidated_at_utc) if entry.invalidated_at_utc else None,
            ),
        )
        if self.search_index is not None:
            with suppress(MemorySearchUnavailableError):
                await self.search_index.upsert_memory_entry(entry, connection=conn)
                # The FTS projection is rebuildable and must not block the
                # authoritative memory write on an unsupported SQLite build.
        return entry

    async def ensure(
        self,
        entry: MemoryEntry,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryEntry:
        """Insert a stable page once and reject silent rewrites under its ID."""

        existing = await self.get(
            entry.account_id,
            entry.character_id,
            entry.memory_id,
            connection=connection,
        )
        if existing is None:
            return await self.insert(entry, connection=connection)
        immutable_fields = (
            "memory_kind",
            "content",
            "confidence",
            "salience",
            "source_kind",
            "source_ref",
            "subject_kind",
            "subject_id",
            "visibility",
            "content_version",
            "occurred_at_utc",
            "expires_at_utc",
        )
        if any(getattr(existing, field) != getattr(entry, field) for field in immutable_fields):
            raise DomainInvariantError("memory entry identity already contains different content")
        if self.search_index is not None:
            with suppress(MemorySearchUnavailableError):
                await self.search_index.upsert_memory_entry(
                    existing, connection=get_connection(self.database, connection)
                )
        return existing

    async def invalidate(
        self,
        account_id: str,
        character_id: str,
        memory_id: str,
        *,
        invalidated_at_utc: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryEntry:
        conn = require_write_connection(connection)
        cursor = await conn.execute(
            """UPDATE memory_entries SET invalidated_at_utc = ?
               WHERE account_id = ? AND character_id = ? AND memory_id = ?
                 AND invalidated_at_utc IS NULL""",
            (
                utc_text(invalidated_at_utc),
                require_non_empty(account_id, "account_id"),
                require_non_empty(character_id, "character_id"),
                require_non_empty(memory_id, "memory_id"),
            ),
        )
        _check_rowcount(cursor.rowcount, "memory entry invalidation")
        entry = await self.get(account_id, character_id, memory_id, connection=conn)
        if entry is None:
            raise RuntimeError("memory entry disappeared after invalidation")
        if self.search_index is not None:
            with suppress(MemorySearchUnavailableError):
                await self.search_index.mark_memory_entry_unsearchable(entry, connection=conn)
        return entry


class DiaryEntryRepository:
    """One private daily record per character and account."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_for_day(
        self,
        account_id: str,
        character_id: str,
        game_day: str,
        connection: aiosqlite.Connection | None = None,
    ) -> DiaryEntry | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            """SELECT * FROM diary_entries
               WHERE account_id = ? AND character_id = ? AND game_day = ?""",
            (account_id, character_id, game_day),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return _diary_from_row(row) if row else None

    async def list_for_character(
        self,
        account_id: str,
        character_id: str,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[DiaryEntry, ...]:
        """List existing daily records for a narrative reflection window."""

        scope = (
            require_non_empty(account_id, "account_id"),
            require_non_empty(character_id, "character_id"),
        )
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM diary_entries WHERE account_id = ? AND character_id = ? "
            "ORDER BY game_day, diary_id",
            scope,
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(_diary_from_row(row) for row in rows)

    async def insert(
        self,
        entry: DiaryEntry,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> DiaryEntry:
        conn = require_write_connection(connection)
        await conn.execute(
            """INSERT INTO diary_entries(
                diary_id, account_id, character_id, game_day, content,
                source_window_kind, source_window_ref, content_version, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(entry.diary_id),
                entry.account_id,
                entry.character_id,
                entry.game_day,
                entry.content,
                entry.source_window_kind,
                entry.source_window_ref,
                entry.content_version,
                utc_text(entry.created_at_utc),
            ),
        )
        return entry

    async def ensure(
        self,
        entry: DiaryEntry,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> DiaryEntry:
        """Make the one-diary-per-day write idempotent."""

        existing = await self.get_for_day(
            entry.account_id,
            entry.character_id,
            entry.game_day,
            connection=connection,
        )
        if existing is None:
            return await self.insert(entry, connection=connection)
        if any(
            getattr(existing, field) != getattr(entry, field)
            for field in ("content", "source_window_kind", "source_window_ref", "content_version")
        ):
            raise DomainInvariantError("diary day already contains different content")
        return existing


class ThoughtRepository:
    """Storage boundary for approved private thought persistence."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def get_by_result(
        self,
        result_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> Thought | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute("SELECT * FROM thoughts WHERE result_id = ?", (str(result_id),))
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return _thought_from_row(row) if row else None

    async def list_for_results(
        self,
        result_ids: tuple[UUID, ...],
        *,
        connection: aiosqlite.Connection,
    ) -> tuple[Thought, ...]:
        if not result_ids:
            return ()
        placeholders = ", ".join("?" for _ in result_ids)
        async with connection.execute(
            f"SELECT * FROM thoughts WHERE result_id IN ({placeholders})",
            tuple(str(result_id) for result_id in result_ids),
        ) as cursor:
            return tuple(_thought_from_row(row) for row in await cursor.fetchall())

    async def list_for_day(
        self,
        account_id: str,
        character_id: str,
        game_day: str,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[Thought, ...]:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            """SELECT * FROM thoughts
               WHERE account_id = ? AND character_id = ? AND game_day = ?
               ORDER BY created_at_utc, thought_id""",
            (account_id, character_id, game_day),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(_thought_from_row(row) for row in rows)

    async def insert(
        self,
        thought: Thought,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> Thought:
        conn = require_write_connection(connection)
        await conn.execute(
            """INSERT INTO thoughts(
                thought_id, result_id, account_id, character_id, game_day, content, created_at_utc,
                conversation_id, content_version, segment_id
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(thought.thought_id),
                str(thought.result_id),
                thought.account_id,
                thought.character_id,
                thought.game_day,
                thought.content,
                utc_text(thought.created_at_utc),
                thought.conversation_id,
                thought.content_version,
                str(thought.segment_id) if thought.segment_id else None,
            ),
        )
        return thought

    async def ensure(
        self,
        thought: Thought,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> Thought:
        """Make a T3 thought write idempotent by its approved result ID."""

        existing = await self.get_by_result(thought.result_id, connection=connection)
        if existing is None:
            return await self.insert(thought, connection=connection)
        if any(
            getattr(existing, field) != getattr(thought, field)
            for field in ("account_id", "character_id", "conversation_id", "game_day", "content")
        ):
            raise DomainInvariantError("thought result identity already contains different content")
        return existing

    async def list_for_segment(
        self, segment_id: UUID, *, connection: aiosqlite.Connection
    ) -> tuple[Thought, ...]:
        async with connection.execute(
            "SELECT * FROM thoughts WHERE segment_id=? ORDER BY created_at_utc,thought_id",
            (str(segment_id),),
        ) as cursor:
            return tuple(_thought_from_row(row) for row in await cursor.fetchall())


def _view_from_row(row: aiosqlite.Row) -> MemoryView:
    refs = json.loads(row["source_refs_json"])
    if not isinstance(refs, list):
        raise DomainInvariantError("memory view source_refs_json must contain a JSON array")
    return MemoryView(
        account_id=row["account_id"],
        character_id=row["character_id"],
        view_kind=MemoryViewKind(row["view_kind"]),
        content=row["content"],
        source_refs=tuple(refs),
        content_version=row["content_version"],
        updated_at_utc=_required_time(row["updated_at_utc"], "updated_at_utc"),
    )


class MemoryViewRepository:
    """Replaceable derived views used by prompt projections."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(
        self,
        account_id: str,
        character_id: str,
        view_kind: MemoryViewKind | str,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryView | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM memory_views WHERE account_id = ? AND character_id = ? "
            "AND view_kind = ?",
            (account_id, character_id, MemoryViewKind(view_kind).value),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return _view_from_row(row) if row else None

    async def get_valid(
        self,
        account_id: str,
        character_id: str,
        view_kind: MemoryViewKind,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection,
    ) -> MemoryView | None:
        from echo_server.store.memory_view_sources import view_source_version

        view = await self.get(account_id, character_id, view_kind, connection)
        if view is None:
            return None
        async with connection.execute(
            "SELECT source_snapshot_version FROM memory_views "
            "WHERE account_id=? AND character_id=? AND view_kind=?",
            (account_id, character_id, view_kind.value),
        ) as cursor:
            stored = await cursor.fetchone()
        version = await view_source_version(view, now_utc=now_utc, connection=connection)
        return view if version is not None and stored[0] == version else None

    async def upsert(
        self,
        view: MemoryView,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryView:
        conn = require_write_connection(connection)
        await conn.execute(
            """INSERT INTO memory_views(
                account_id, character_id, view_kind, content, source_refs_json,
                content_version, updated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, character_id, view_kind) DO UPDATE SET
                content = excluded.content,
                source_refs_json = excluded.source_refs_json,
                content_version = excluded.content_version,
                updated_at_utc = excluded.updated_at_utc""",
            (
                view.account_id,
                view.character_id,
                view.view_kind.value,
                view.content,
                as_json(list(view.source_refs)),
                view.content_version,
                utc_text(view.updated_at_utc),
            ),
        )
        from echo_server.store.memory_view_sources import view_source_version

        version = await view_source_version(view, now_utc=view.updated_at_utc, connection=conn)
        await conn.execute(
            "UPDATE memory_views SET source_snapshot_version=? "
            "WHERE account_id=? AND character_id=? AND view_kind=?",
            (version, view.account_id, view.character_id, view.view_kind.value),
        )
        stored = await self.get(
            view.account_id,
            view.character_id,
            view.view_kind,
            connection=conn,
        )
        if stored is None:
            raise RuntimeError("memory view was not persisted")
        return stored


class MemoryGraphRepository:
    """Write/read access to graph indexes derived from memory pages."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def upsert_entity(
        self,
        entity: MemoryEntity,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryEntity:
        conn = require_write_connection(connection)
        await conn.execute(
            """INSERT INTO memory_entities(
                account_id, character_id, entity_id, entity_kind, canonical_name,
                created_at_utc, updated_at_utc, invalidated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)
            ON CONFLICT(account_id, character_id, entity_id) DO UPDATE SET
                entity_kind = excluded.entity_kind,
                canonical_name = excluded.canonical_name,
                updated_at_utc = excluded.updated_at_utc,
                invalidated_at_utc = excluded.invalidated_at_utc""",
            (
                entity.account_id,
                entity.character_id,
                entity.entity_id,
                entity.entity_kind,
                entity.canonical_name,
                utc_text(entity.created_at_utc),
                utc_text(entity.updated_at_utc),
                utc_text(entity.invalidated_at_utc) if entity.invalidated_at_utc else None,
            ),
        )
        return entity

    async def get_entity(
        self,
        account_id: str,
        character_id: str,
        entity_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryEntity | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            """SELECT * FROM memory_entities
               WHERE account_id = ? AND character_id = ? AND entity_id = ?""",
            (account_id, character_id, entity_id),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return _entity_from_row(row) if row else None

    async def find_entity_by_alias(
        self,
        account_id: str,
        character_id: str,
        normalized_alias: str,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryEntity | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            """SELECT e.* FROM memory_entities e
               JOIN memory_entity_aliases a
                 ON a.account_id=e.account_id AND a.character_id=e.character_id
                AND a.entity_id=e.entity_id
               WHERE e.account_id=? AND e.character_id=?
                 AND a.normalized_alias=? AND a.invalidated_at_utc IS NULL
                 AND e.invalidated_at_utc IS NULL""",
            (account_id, character_id, normalized_alias),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return _entity_from_row(row) if row else None

    async def add_alias(
        self,
        alias: MemoryEntityAlias,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryEntityAlias:
        conn = require_write_connection(connection)
        existing_cursor = await conn.execute(
            """SELECT * FROM memory_entity_aliases
               WHERE account_id = ? AND character_id = ? AND normalized_alias = ?""",
            (alias.account_id, alias.character_id, alias.normalized_alias),
        )
        try:
            existing = await existing_cursor.fetchone()
        finally:
            await existing_cursor.close()
        if (
            existing is not None
            and existing["invalidated_at_utc"] is None
            and existing["entity_id"] != alias.entity_id
        ):
            raise DomainInvariantError("memory alias already points to another entity")
        if existing is not None and existing["invalidated_at_utc"] is None:
            return alias
        await conn.execute(
            """INSERT INTO memory_entity_aliases(
                alias_id, account_id, character_id, entity_id, alias_text,
                normalized_alias, created_at_utc, invalidated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(alias.alias_id),
                alias.account_id,
                alias.character_id,
                alias.entity_id,
                alias.alias_text,
                alias.normalized_alias,
                utc_text(alias.created_at_utc),
                utc_text(alias.invalidated_at_utc) if alias.invalidated_at_utc else None,
            ),
        )
        return alias

    async def link_entry_entity(
        self,
        link: MemoryEntryEntityLink,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryEntryEntityLink:
        conn = require_write_connection(connection)
        await conn.execute(
            """INSERT OR IGNORE INTO memory_entry_entities(
                account_id, character_id, memory_id, entity_id, role, created_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?)""",
            (
                link.account_id,
                link.character_id,
                link.memory_id,
                link.entity_id,
                link.role,
                utc_text(link.created_at_utc),
            ),
        )
        return link

    async def add_edge(
        self,
        edge: MemoryEdge,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> MemoryEdge:
        conn = require_write_connection(connection)
        existing_cursor = await conn.execute(
            """SELECT * FROM memory_edges
               WHERE account_id = ? AND character_id = ? AND from_entity_id = ?
                 AND to_entity_id = ? AND edge_kind = ?
                 AND ((source_memory_id IS NULL AND ? IS NULL) OR source_memory_id = ?)""",
            (
                edge.account_id,
                edge.character_id,
                edge.from_entity_id,
                edge.to_entity_id,
                edge.edge_kind,
                edge.source_memory_id,
                edge.source_memory_id,
            ),
        )
        try:
            existing = await existing_cursor.fetchone()
        finally:
            await existing_cursor.close()
        if existing is not None:
            if existing["edge_id"] != str(edge.edge_id):
                raise DomainInvariantError("memory edge identity already contains another edge")
            return edge
        await conn.execute(
            """INSERT INTO memory_edges(
                edge_id, account_id, character_id, from_entity_id, to_entity_id,
                edge_kind, confidence, source_memory_id, created_at_utc, invalidated_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(edge.edge_id),
                edge.account_id,
                edge.character_id,
                edge.from_entity_id,
                edge.to_entity_id,
                edge.edge_kind,
                edge.confidence,
                edge.source_memory_id,
                utc_text(edge.created_at_utc),
                utc_text(edge.invalidated_at_utc) if edge.invalidated_at_utc else None,
            ),
        )
        return edge

    async def list_edges_for_entity(
        self,
        account_id: str,
        character_id: str,
        entity_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[MemoryEdge, ...]:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            """SELECT * FROM memory_edges
               WHERE account_id = ? AND character_id = ?
                 AND (from_entity_id = ? OR to_entity_id = ?)
                 AND invalidated_at_utc IS NULL
               ORDER BY created_at_utc, edge_id""",
            (account_id, character_id, entity_id, entity_id),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(_edge_from_row(row) for row in rows)


__all__ = [
    "DiaryEntryRepository",
    "MemoryEntryRepository",
    "MemoryGraphRepository",
    "MemorySegmentRepository",
    "MemoryViewRepository",
    "ThoughtRepository",
]
