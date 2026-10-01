from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

import pytest
import pytest_asyncio

from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.domain.memory import (
    MemoryEdge,
    MemoryEntity,
    MemoryEntry,
    MemoryEntryEntityLink,
    MemorySegment,
    MemorySegmentStatus,
)
from echo_server.domain.task import ConversationTask
from echo_server.runtime.application_runtime import ApplicationRuntime
from echo_server.services.context import RepositoryContextSource
from echo_server.services.identity import load_identity_catalog
from echo_server.services.memory import MemoryInitializationService
from echo_server.store.database import Database
from echo_server.store.memory_repositories import (
    MemoryEntryRepository,
    MemoryGraphRepository,
    MemorySegmentRepository,
)
from echo_server.store.migrations import migrate
from echo_server.store.runtime_repositories import CharacterStateRepository, WorldStateRepository
from echo_server.store.state_repositories import (
    CharacterStateEntryRepository,
    RelationshipStateRepository,
)

BASE_TIME = datetime(2026, 9, 16, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def database(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await migrate(database)
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_authored_preload_is_idempotent_and_only_resident_pages_enter_context(database):
    catalog = load_identity_catalog()
    entries = MemoryEntryRepository(database)
    initializer = MemoryInitializationService(entries, catalog)

    async with database.transaction(immediate=True) as connection:
        first_count = await initializer.ensure_account_preload(
            "account-1",
            now_utc=BASE_TIME,
            connection=connection,
        )
    async with database.transaction(immediate=True) as connection:
        second_count = await initializer.ensure_account_preload(
            "account-1",
            now_utc=BASE_TIME,
            connection=connection,
        )

    assert (first_count, second_count) == (4, 4)
    all_entries = await entries.list_for_scope("account-1", "xiaojin")
    assert len(all_entries) == 4
    resident, version = await entries.list_resident(
        "account-1",
        "xiaojin",
        now_utc=BASE_TIME,
    )
    assert {entry.memory_id for entry in resident} == {
        "xiaojin.preload.livelihood",
        "xiaojin.preload.home",
        "xiaojin.preload.painting-anchor",
    }
    assert version.startswith("3:")

    source = RepositoryContextSource(
        WorldStateRepository(database),
        CharacterStateRepository(database),
        CharacterStateEntryRepository(database),
        RelationshipStateRepository(database),
        entries,
    )
    task = ConversationTask.create(
        task_id=uuid4(),
        account_id="account-1",
        conversation_id="conversation-1",
        character_id="xiaojin",
        input_max_message_sequence=1,
        context_max_message_sequence=1,
        world_state_version=0,
        character_state_version=0,
        context_version="1",
        trace_id=uuid4(),
        now_utc=BASE_TIME,
    )
    async with database.transaction() as connection:
        snapshot = await source.load(task, now_utc=BASE_TIME, connection=connection)
    assert len(snapshot.memory_context.resident) == 3
    assert snapshot.memory_context.recalled == ()
    assert snapshot.relationship_state.relationship_type == "stranger"
    assert any(source.source == "memory.resident" for source in snapshot.source_versions)


@pytest.mark.asyncio
async def test_runtime_start_bootstraps_authored_memory_without_initializing_relationships(
    tmp_path,
):
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        worker_enabled=False,
    )
    runtime = ApplicationRuntime(Database(settings.database_path), StubCharacterAgent(), settings)
    await runtime.start()
    try:
        rows = await runtime.database.fetchall(
            "SELECT memory_id, source_kind FROM memory_entries "
            "WHERE account_id = ? AND character_id = ? ORDER BY memory_id",
            (settings.account_id, settings.default_character_id),
        )
        assert len(rows) == 4
        assert {row["source_kind"] for row in rows} == {"authored_preload"}
        relationship_count = await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM relationship_state WHERE account_id = ?",
            (settings.account_id,),
        )
        assert relationship_count["count"] == 0
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_memory_segment_keeps_message_window_separate_from_page_content(database):
    await database.execute(
        "INSERT INTO conversations(account_id, conversation_id, context_version, "
        "created_at_utc, updated_at_utc, kind, status) VALUES "
        "('account-1', 'conversation-1', '1', ?, ?, 'direct', 'active')",
        (BASE_TIME.isoformat(), BASE_TIME.isoformat()),
    )
    await database.execute(
        "INSERT INTO character_states(character_id, availability_status, state_version, "
        "updated_at_utc) VALUES ('xiaojin', 'available', 0, ?)",
        (BASE_TIME.isoformat(),),
    )
    await database.require_connection().commit()

    segment = MemorySegment(
        segment_id=uuid4(),
        account_id="account-1",
        conversation_id="conversation-1",
        character_id="xiaojin",
        first_message_sequence=1,
        last_message_sequence=4,
        status=MemorySegmentStatus.SEALED,
        source_version="conversation:4",
        sealed_at_utc=BASE_TIME,
        created_at_utc=BASE_TIME,
        updated_at_utc=BASE_TIME,
    )
    repository = MemorySegmentRepository(database)
    async with database.transaction(immediate=True) as connection:
        await repository.create(segment, connection=connection)
    stored = await repository.get(segment.segment_id)
    assert stored == segment
    assert stored.summary_text is None


@pytest.mark.asyncio
async def test_graph_rows_reference_pages_and_can_be_read_back(database):
    entries = MemoryEntryRepository(database)
    entry = MemoryEntry(
        account_id="account-1",
        character_id="xiaojin",
        memory_id="memory-1",
        memory_kind="fact",
        content="小槿靠画画维持生活。",
        source_kind="authored_preload",
        source_ref="test:memory-1",
        subject_kind="character",
        subject_id="xiaojin",
        visibility="resident",
        content_version="0.1.0-draft",
        recorded_at_utc=BASE_TIME,
    )
    first_entity = MemoryEntity(
        account_id="account-1",
        character_id="xiaojin",
        entity_id="xiaojin",
        entity_kind="character",
        canonical_name="小槿",
        created_at_utc=BASE_TIME,
        updated_at_utc=BASE_TIME,
    )
    second_entity = MemoryEntity(
        account_id="account-1",
        character_id="xiaojin",
        entity_id="painting",
        entity_kind="activity",
        canonical_name="画画",
        created_at_utc=BASE_TIME,
        updated_at_utc=BASE_TIME,
    )
    graph = MemoryGraphRepository(database)
    async with database.transaction(immediate=True) as connection:
        await entries.insert(entry, connection=connection)
        await graph.upsert_entity(first_entity, connection=connection)
        await graph.upsert_entity(second_entity, connection=connection)
        await graph.link_entry_entity(
            MemoryEntryEntityLink(
                account_id="account-1",
                character_id="xiaojin",
                memory_id="memory-1",
                entity_id="painting",
                role="topic",
                created_at_utc=BASE_TIME,
            ),
            connection=connection,
        )
        edge = MemoryEdge(
            edge_id=uuid4(),
            account_id="account-1",
            character_id="xiaojin",
            from_entity_id="xiaojin",
            to_entity_id="painting",
            edge_kind="does",
            confidence=1.0,
            source_memory_id="memory-1",
            created_at_utc=BASE_TIME,
        )
        await graph.add_edge(edge, connection=connection)
    assert await graph.get_entity("account-1", "xiaojin", "painting") == second_entity
    assert (await graph.list_edges_for_entity("account-1", "xiaojin", "xiaojin"))[
        0
    ].source_memory_id == ("memory-1")
