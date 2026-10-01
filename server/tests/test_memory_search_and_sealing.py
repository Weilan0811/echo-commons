from __future__ import annotations

from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from support_xiaojin import build_xiaojin_snapshot, load_xiaojin_fixture_turns

from echo_server.agents.contracts import MemoryAccessPolicy
from echo_server.agents.harness.tools import ToolContext
from echo_server.config import Settings
from echo_server.domain.memory import MemoryEntry
from echo_server.runtime.application_runtime import ApplicationRuntime
from echo_server.runtime.memory import MemorySearchTool
from echo_server.services.identity import load_identity_catalog
from echo_server.services.memory import MemorySearchScope, MemorySearchService
from echo_server.store.database import Database
from echo_server.store.memory_repositories import MemoryEntryRepository
from echo_server.store.memory_search_repositories import MemorySearchUnavailableError
from echo_server.store.migrations import migrate

BASE_TIME = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def database(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await migrate(database)
    yield database
    await database.close()


async def _prepare_conversation(database: Database, *, account_id: str = "account-1") -> None:
    connection = database.require_connection()
    await connection.execute(
        """INSERT INTO conversations(
            account_id, conversation_id, context_version, created_at_utc, updated_at_utc,
            kind, status
        ) VALUES (?, 'conversation-1', '1', ?, ?, 'direct', 'active')""",
        (account_id, BASE_TIME.isoformat(), BASE_TIME.isoformat()),
    )
    await connection.execute(
        """INSERT INTO character_states(
            character_id, availability_status, state_version, updated_at_utc
        ) VALUES ('xiaojin', 'available', 0, ?)""",
        (BASE_TIME.isoformat(),),
    )
    await connection.execute(
        """INSERT INTO conversation_participants(
            account_id, conversation_id, character_id, joined_at_utc
        ) VALUES (?, 'conversation-1', 'xiaojin', ?)""",
        (account_id, BASE_TIME.isoformat()),
    )
    await connection.commit()


async def _insert_raw_message(
    database: Database,
    *,
    sequence_text: str,
    account_id: str = "account-1",
) -> None:
    connection = database.require_connection()
    await connection.execute(
        """INSERT INTO messages(
            message_id, account_id, conversation_id, sender_type, sender_id, text,
            images_json, server_timestamp_utc, trace_id
        ) VALUES (?, ?, 'conversation-1', 'player', ?, ?, '[]', ?, ?)""",
        (
            str(uuid4()),
            account_id,
            account_id,
            sequence_text,
            (BASE_TIME + timedelta(seconds=1)).isoformat(),
            str(uuid4()),
        ),
    )
    await connection.commit()


@pytest.mark.asyncio
async def test_seal_unsegmented_messages_is_idempotent_and_scoped(database):
    await _prepare_conversation(database)
    await _insert_raw_message(database, sequence_text="第一次见面")
    await _insert_raw_message(database, sequence_text="聊到画画")

    runtime = ApplicationRuntime(
        database,
        agent=object(),  # only the sealing facade is used in this test
        settings=Settings(worker_enabled=False),
    )
    first = await runtime.memory_sealing.seal_unsegmented_messages(
        "account-1",
        "conversation-1",
        "xiaojin",
        now_utc=BASE_TIME,
    )
    assert first is not None
    assert (first.first_message_sequence, first.last_message_sequence) == (1, 2)
    assert first.status.value == "sealed"

    second = await runtime.memory_sealing.seal_unsegmented_messages(
        "account-1",
        "conversation-1",
        "xiaojin",
        now_utc=BASE_TIME,
    )
    assert second is None


@pytest.mark.asyncio
async def test_seal_can_freeze_a_prefix_then_continue_with_the_suffix(database):
    await _prepare_conversation(database)
    await _insert_raw_message(database, sequence_text="前缀消息")
    await _insert_raw_message(database, sequence_text="后续消息")

    runtime = ApplicationRuntime(
        database,
        agent=object(),
        settings=Settings(worker_enabled=False),
    )
    first = await runtime.memory_sealing.seal_unsegmented_messages(
        "account-1",
        "conversation-1",
        "xiaojin",
        through_sequence=1,
        now_utc=BASE_TIME,
    )
    assert first is not None
    assert (first.first_message_sequence, first.last_message_sequence) == (1, 1)

    second = await runtime.memory_sealing.seal_unsegmented_messages(
        "account-1",
        "conversation-1",
        "xiaojin",
        now_utc=BASE_TIME,
    )
    assert second is not None
    assert (second.first_message_sequence, second.last_message_sequence) == (2, 2)


@pytest.mark.asyncio
async def test_memory_search_uses_fts_and_excludes_private_pages(database):
    search = MemorySearchService(database)
    entries = MemoryEntryRepository(database, search_index=search)
    public = MemoryEntry(
        account_id="account-1",
        character_id="xiaojin",
        memory_id="memory-public",
        memory_kind="preference",
        content="小槿喜欢在画画后买甜点。",
        source_kind="authored_preload",
        source_ref="preload:public",
        subject_kind="character",
        subject_id="xiaojin",
        visibility="recallable",
        content_version="v1",
        recorded_at_utc=BASE_TIME,
    )
    private = replace(
        public,
        memory_id="memory-private",
        content="这是不应被角色普通检索看到的秘密。",
        source_ref="preload:private",
        visibility="private",
    )
    async with database.transaction(immediate=True) as connection:
        await entries.insert(public, connection=connection)
        await entries.insert(private, connection=connection)

    hits = await search.search(
        MemorySearchScope("account-1", "xiaojin"),
        "甜点",
        now_utc=BASE_TIME,
    )
    assert hits
    assert hits[0].memory_id == "memory-public"
    assert all(hit.memory_id != "memory-private" for hit in hits)
    assert hits[0].retrieval_kind == "fts5"


@pytest.mark.asyncio
async def test_memory_search_tool_uses_runtime_bound_scope(database):
    search = MemorySearchService(database)
    entries = MemoryEntryRepository(database, search_index=search)
    entry = MemoryEntry(
        account_id="local-player",
        character_id="xiaojin",
        memory_id="memory-tool",
        memory_kind="event",
        content="她记得和对方一起看过湖边的夜景。",
        source_kind="reflection",
        source_ref="message:source",
        subject_kind="account",
        subject_id="local-player",
        visibility="recallable",
        content_version="v1",
        recorded_at_utc=BASE_TIME,
    )
    async with database.transaction(immediate=True) as connection:
        await entries.insert(entry, connection=connection)

    settings = Settings(database_path=database.path, worker_enabled=False)
    runtime = ApplicationRuntime(database, agent=object(), settings=settings)
    tool = MemorySearchTool(runtime.memory_search, account_id="local-player")
    snapshot = build_xiaojin_snapshot(
        load_identity_catalog(),
        load_xiaojin_fixture_turns()[0],
    )
    unauthorized_context = ToolContext(
        invocation_id=uuid4(),
        agent_id="xiaojin.character",
        call_id="call-unauthorized",
        tool_name=tool.name,
        snapshot=snapshot,
    )
    unauthorized = await tool.invoke({"query": "湖边夜景"}, unauthorized_context)
    assert unauthorized.ok is False
    assert unauthorized.error_code == "memory_search_not_authorized"
    snapshot = snapshot.model_copy(
        update={
            "memory_context": snapshot.memory_context.model_copy(
                update={
                    "access_policy": MemoryAccessPolicy(
                        search_enabled=True,
                        search_tool_name=tool.name,
                        max_results=5,
                    )
                }
            )
        }
    )
    context = ToolContext(
        invocation_id=uuid4(),
        agent_id="xiaojin.character",
        call_id="call-1",
        tool_name=tool.name,
        snapshot=snapshot,
    )
    result = await tool.invoke({"query": "湖边夜景", "limit": 1}, context)
    assert result.ok is True
    assert result.output["results"][0]["memoryId"] == "memory-tool"
    assert all("content" not in hit for hit in result.output["results"])


@pytest.mark.asyncio
async def test_memory_invalidation_removes_page_from_sparse_search(database):
    search = MemorySearchService(database)
    entries = MemoryEntryRepository(database, search_index=search)
    entry = MemoryEntry(
        account_id="account-1",
        character_id="xiaojin",
        memory_id="memory-invalidate",
        memory_kind="fact",
        content="她喜欢在雨天听音乐。",
        source_kind="reflection",
        source_ref="message:rain",
        subject_kind="character",
        subject_id="xiaojin",
        visibility="recallable",
        content_version="v1",
        recorded_at_utc=BASE_TIME,
    )
    async with database.transaction(immediate=True) as connection:
        await entries.insert(entry, connection=connection)
    assert await search.search(
        MemorySearchScope("account-1", "xiaojin"),
        "雨天音乐",
        now_utc=BASE_TIME,
    )

    async with database.transaction(immediate=True) as connection:
        await entries.invalidate(
            "account-1",
            "xiaojin",
            "memory-invalidate",
            invalidated_at_utc=BASE_TIME + timedelta(minutes=1),
            connection=connection,
        )
    assert not await search.search(
        MemorySearchScope("account-1", "xiaojin"),
        "雨天音乐",
        now_utc=BASE_TIME,
    )


@pytest.mark.asyncio
async def test_memory_search_falls_back_to_structured_filter(monkeypatch, database):
    search = MemorySearchService(database)
    entries = MemoryEntryRepository(database, search_index=search)
    entry = MemoryEntry(
        account_id="account-1",
        character_id="xiaojin",
        memory_id="memory-fallback",
        memory_kind="event",
        content="她曾在湖边看过夜景。",
        source_kind="reflection",
        source_ref="message:lake",
        subject_kind="account",
        subject_id="account-1",
        visibility="recallable",
        content_version="v1",
        recorded_at_utc=BASE_TIME,
    )
    async with database.transaction(immediate=True) as connection:
        await entries.insert(entry, connection=connection)

    async def unavailable(*args, **kwargs):
        raise MemorySearchUnavailableError("test")

    monkeypatch.setattr(search.repository, "search", unavailable)
    hits = await search.search(
        MemorySearchScope("account-1", "xiaojin"),
        "湖边夜景",
        now_utc=BASE_TIME,
    )
    assert hits
    assert hits[0].memory_id == "memory-fallback"
    assert hits[0].retrieval_kind == "structured"


@pytest.mark.asyncio
async def test_sparse_rebuild_preserves_source_document_identity(database):
    search = MemorySearchService(database)
    entries = MemoryEntryRepository(database, search_index=search)
    entry = MemoryEntry(
        account_id="account-1",
        character_id="xiaojin",
        memory_id="memory-stable-document",
        memory_kind="fact",
        content="稳定来源映射应跨索引重建保留。",
        source_kind="reflection",
        source_ref="message:stable",
        subject_kind="character",
        subject_id="xiaojin",
        visibility="recallable",
        content_version="v1",
        recorded_at_utc=BASE_TIME,
    )
    async with database.transaction(immediate=True) as connection:
        await entries.insert(entry, connection=connection)
    before = await database.fetchone(
        "SELECT document_id FROM memory_search_documents "
        "WHERE account_id = ? AND character_id = ? AND source_kind = 'memory_entry' "
        "AND source_id = ?",
        ("account-1", "xiaojin", "memory-stable-document"),
    )
    async with database.transaction(immediate=True) as connection:
        await search.rebuild_scope("account-1", "xiaojin", connection=connection)
    after = await database.fetchone(
        "SELECT document_id FROM memory_search_documents "
        "WHERE account_id = ? AND character_id = ? AND source_kind = 'memory_entry' "
        "AND source_id = ?",
        ("account-1", "xiaojin", "memory-stable-document"),
    )
    assert before is not None and after is not None
    assert before["document_id"] == after["document_id"]
    hits = await search.search(
        MemorySearchScope("account-1", "xiaojin"),
        "稳定来源",
        now_utc=BASE_TIME,
    )
    assert hits and hits[0].memory_id == "memory-stable-document"


@pytest.mark.asyncio
async def test_runtime_start_rebuilds_sparse_index_for_preloaded_memory(tmp_path):
    settings = Settings(database_path=str(tmp_path / "echo.sqlite3"), worker_enabled=False)
    runtime = ApplicationRuntime(
        Database(settings.database_path), agent=object(), settings=settings
    )
    await runtime.start()
    try:
        hits = await runtime.memory_search.search(
            MemorySearchScope(settings.account_id, settings.default_character_id),
            "画画",
            now_utc=BASE_TIME,
        )
        assert hits
    finally:
        await runtime.stop()
