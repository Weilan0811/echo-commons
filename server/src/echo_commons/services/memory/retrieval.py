from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime

import aiosqlite

from echo_commons.domain.memory import MemoryEntry, MemoryVisibility
from echo_commons.domain.messages import Message, SenderType
from echo_commons.store.database import Database
from echo_commons.store.memory_search_repositories import (
    MAX_SEARCH_DISPLAY_CHARS,
    MemorySearchRepository,
    MemorySearchRow,
    MemorySearchUnavailableError,
)
from echo_commons.store.repository_support import parse_time

from echo_commons.modules.memory.services.tokenization import (
    fts_match_query, tokenize_text, tokenized_text,
)


@dataclass(frozen=True, slots=True)
class MemorySearchScope:
    account_id: str
    character_id: str
    conversation_id: str | None = None


@dataclass(frozen=True, slots=True)
class MemorySearchHit:
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
    retrieval_policy_version: str = "sparse-v2"


class MemorySourceChangedError(RuntimeError):
    """The invocation must keep its existing context instead of mixing source versions."""


class MemorySearchService:
    """Stable search boundary for sparse, dense, and graph retrievers."""

    def __init__(
        self,
        database: Database,
        repository: MemorySearchRepository | None = None,
    ) -> None:
        self.database = database
        self.repository = repository or MemorySearchRepository(database)

    async def upsert_memory_entry(
        self,
        entry: MemoryEntry,
        *,
        connection: aiosqlite.Connection,
    ) -> None:
        searchable = entry.visibility in (
            MemoryVisibility.RESIDENT,
            MemoryVisibility.RECALLABLE,
        ) and entry.is_active_at(entry.recorded_at_utc)
        await self.repository.upsert_document(
            account_id=entry.account_id,
            character_id=entry.character_id,
            conversation_id=None,
            source_kind="memory_entry",
            source_id=entry.memory_id,
            source_version=entry.content_version,
            occurred_at_utc=entry.occurred_at_utc or entry.recorded_at_utc,
            tokenized_text=tokenized_text(entry.content) if searchable else "",
            display_text=entry.content[:MAX_SEARCH_DISPLAY_CHARS],
            searchable=searchable,
            updated_at_utc=entry.recorded_at_utc,
            connection=connection,
        )

    async def upsert_message(
        self,
        message: Message,
        *,
        connection: aiosqlite.Connection,
    ) -> None:
        if message.sender.type not in (SenderType.PLAYER, SenderType.CHARACTER):
            return
        character_ids = await self.repository.list_conversation_character_ids(
            message.account_id,
            message.conversation_id,
            connection=connection,
        )
        for character_id in character_ids:
            await self.repository.upsert_document(
                account_id=message.account_id,
                character_id=character_id,
                conversation_id=message.conversation_id,
                source_kind="message",
                source_id=str(message.message_id),
                source_version=str(message.message_id),
                occurred_at_utc=message.server_timestamp_utc,
                tokenized_text=tokenized_text(message.text),
                display_text=message.text[:MAX_SEARCH_DISPLAY_CHARS],
                searchable=bool(tokenize_text(message.text)),
                updated_at_utc=message.server_timestamp_utc,
                connection=connection,
            )

    async def mark_memory_entry_unsearchable(
        self,
        entry: MemoryEntry,
        *,
        connection: aiosqlite.Connection,
    ) -> None:
        await self.repository.mark_unsearchable(
            account_id=entry.account_id,
            character_id=entry.character_id,
            source_kind="memory_entry",
            source_id=entry.memory_id,
            updated_at_utc=entry.invalidated_at_utc or entry.recorded_at_utc,
            connection=connection,
        )

    async def search(
        self,
        scope: MemorySearchScope,
        query: str,
        *,
        limit: int = 5,
        now_utc: datetime,
        connection: aiosqlite.Connection | None = None,
        expected_source_version: str | None = None,
        frozen_conversation_id: str | None = None,
        frozen_max_sequence: int | None = None,
    ) -> tuple[MemorySearchHit, ...]:
        if connection is None:
            async with self.database.transaction() as connection:
                return await self.search(
                    scope,
                    query,
                    limit=limit,
                    now_utc=now_utc,
                    connection=connection,
                    expected_source_version=expected_source_version,
                    frozen_conversation_id=frozen_conversation_id,
                    frozen_max_sequence=frozen_max_sequence,
                )
        if expected_source_version is not None:
            current = await self.source_version(
                scope,
                now_utc=now_utc,
                connection=connection,
                frozen_conversation_id=frozen_conversation_id,
                frozen_max_sequence=frozen_max_sequence,
            )
            if current != expected_source_version:
                raise MemorySourceChangedError("memory_source_changed")
        bounded_limit = max(1, min(int(limit), 50))
        terms = tokenize_text(query)
        if not terms:
            return ()
        match_query = fts_match_query(query)
        if match_query is None:
            return ()
        try:
            rows = await self.repository.search(
                account_id=scope.account_id,
                character_id=scope.character_id,
                match_query=match_query,
                now_utc=now_utc,
                limit=bounded_limit,
                conversation_id=scope.conversation_id,
                frozen_conversation_id=frozen_conversation_id,
                frozen_max_sequence=frozen_max_sequence,
                connection=connection,
            )
        except MemorySearchUnavailableError:
            rows = await self.repository.structured_search(
                account_id=scope.account_id,
                character_id=scope.character_id,
                terms=terms,
                now_utc=now_utc,
                limit=bounded_limit,
                conversation_id=scope.conversation_id,
                frozen_conversation_id=frozen_conversation_id,
                frozen_max_sequence=frozen_max_sequence,
                connection=connection,
            )
        return tuple(_hit_from_row(row) for row in rows)

    async def source_version(
        self,
        scope: MemorySearchScope,
        *,
        now_utc: datetime,
        connection: aiosqlite.Connection,
        frozen_conversation_id: str | None = None,
        frozen_max_sequence: int | None = None,
    ) -> str:
        from echo_commons.domain.memory_sources import content_version

        memories = await self.repository.list_memory_entry_rows(
            scope.account_id, scope.character_id, connection=connection
        )
        pages = sorted(
            (r["memory_id"], r["content_version"], r["content"], r["visibility"])
            for r in memories
            if r["visibility"] in ("resident", "recallable")
            and _memory_entry_from_row(r).is_active_at(now_utc)
        )
        messages = await self.repository.list_message_rows_for_character(
            scope.account_id, scope.character_id, connection=connection
        )
        history = [
            (r["message_id"], r["text"], r["conversation_id"])
            for r in messages
            if (scope.conversation_id is None or r["conversation_id"] == scope.conversation_id)
            and (
                r["conversation_id"] != frozen_conversation_id
                or r["message_sequence"] <= frozen_max_sequence
            )
        ]
        return content_version(
            (
                "sparse-v2",
                scope.account_id,
                scope.character_id,
                scope.conversation_id,
                frozen_conversation_id,
                frozen_max_sequence,
                pages,
                history,
            )
        )

    async def rebuild_scope(
        self,
        account_id: str,
        character_id: str,
        *,
        connection: aiosqlite.Connection,
    ) -> None:
        """Rebuild one account/character projection from authoritative tables."""

        await self.repository.rebuild_scope(account_id, character_id, connection=connection)
        memory_rows = await self.repository.list_memory_entry_rows(
            account_id,
            character_id,
            connection=connection,
        )
        for row in memory_rows:
            entry = _memory_entry_from_row(row)
            await self.upsert_memory_entry(entry, connection=connection)

        message_rows = await self.repository.list_message_rows_for_character(
            account_id,
            character_id,
            connection=connection,
        )
        for row in message_rows:
            message = _message_from_row(row)
            await self.repository.upsert_document(
                account_id=account_id,
                character_id=character_id,
                conversation_id=message.conversation_id,
                source_kind="message",
                source_id=str(message.message_id),
                source_version=str(message.message_id),
                occurred_at_utc=message.server_timestamp_utc,
                tokenized_text=tokenized_text(message.text),
                display_text=message.text[:MAX_SEARCH_DISPLAY_CHARS],
                searchable=bool(tokenize_text(message.text)),
                updated_at_utc=message.server_timestamp_utc,
                connection=connection,
            )


def _hit_from_row(row: MemorySearchRow) -> MemorySearchHit:
    return MemorySearchHit(
        source_kind=row.source_kind,
        content_version=row.content_version,
        source_id=row.source_id,
        source_ref=row.source_ref,
        memory_id=row.memory_id,
        memory_kind=row.memory_kind,
        summary=row.summary,
        occurred_at_utc=row.occurred_at_utc,
        score=row.score,
        retrieval_kind=row.retrieval_kind,
        conversation_id=row.conversation_id,
    )


def _memory_entry_from_row(row: aiosqlite.Row) -> MemoryEntry:
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
        occurred_at_utc=parse_time(row["occurred_at_utc"]),
        recorded_at_utc=parse_time(row["recorded_at_utc"]),
        expires_at_utc=parse_time(row["expires_at_utc"]),
        invalidated_at_utc=parse_time(row["invalidated_at_utc"]),
    )


def _message_from_row(row: aiosqlite.Row) -> Message:
    import json
    from uuid import UUID

    from echo_commons.domain.messages import MessageSender

    return Message(
        message_sequence=int(row["message_sequence"]),
        message_id=UUID(row["message_id"]),
        account_id=row["account_id"],
        conversation_id=row["conversation_id"],
        sender=MessageSender(type=row["sender_type"], id=row["sender_id"]),
        text=row["text"],
        images=tuple(json.loads(row["images_json"])),
        client_msg_id=UUID(row["client_msg_id"]) if row["client_msg_id"] else None,
        client_timestamp_utc=parse_time(row["client_timestamp_utc"]),
        server_timestamp_utc=parse_time(row["server_timestamp_utc"]),
        reply_to_message_id=UUID(row["reply_to_message_id"])
        if row["reply_to_message_id"]
        else None,
        trace_id=UUID(row["trace_id"]),
        input_batch_id=UUID(row["input_batch_id"]) if row["input_batch_id"] else None,
        result_id=UUID(row["result_id"]) if row["result_id"] else None,
        bubble_index=row["bubble_index"],
    )


__all__ = ["MemorySearchHit", "MemorySearchScope", "MemorySearchService"]
