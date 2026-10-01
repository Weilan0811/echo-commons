from __future__ import annotations

import sqlite3

import pytest

from echo_commons.store.database import Database
from echo_commons.store.migrations import MIGRATIONS_DIR, _statements, migrate

LEGACY_M0_TABLES = ("conversation_turns", "situation_proposals", "agent_proposals")


async def assert_legacy_m0_persistence_removed(database: Database) -> None:
    for table in LEGACY_M0_TABLES:
        assert (
            await database.fetchone(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            )
            is None
        )

    columns = {row["name"] for row in await database.fetchall("PRAGMA table_info(conversations)")}
    assert {"character_id", "stage_summary"}.isdisjoint(columns)
    assert {
        "account_id",
        "conversation_id",
        "context_version",
        "created_at_utc",
        "updated_at_utc",
        "kind",
        "status",
    } <= columns
    assert await database.fetchone("SELECT 1 FROM meta WHERE key = 'state_version'") is None


@pytest.mark.asyncio
async def test_fresh_migration_exposes_only_canonical_persistence(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await migrate(database)

    await assert_legacy_m0_persistence_removed(database)
    for table in (
        "conversations",
        "messages",
        "world_state",
        "character_states",
        "character_state_entries",
        "relationship_state",
        "relation_evidence",
        "conversation_participants",
        "conversation_tasks",
        "input_batches",
        "agent_results",
        "traces",
        "trace_outbox",
        "memory_segments",
        "memory_entries",
        "diary_entries",
        "thoughts",
        "memory_entities",
        "memory_entity_aliases",
        "memory_entry_entities",
        "memory_edges",
        "memory_search_documents",
        "memory_search_fts",
        "reflection_graph_runs",
        "reflection_node_tasks",
        "reflection_artifacts",
        "reflection_graph_results",
        "memory_views",
    ):
        assert (
            await database.fetchone(
                "SELECT 1 FROM sqlite_master WHERE type = 'table' AND name = ?", (table,)
            )
            is not None
        )
    assert {
        row["version"] for row in await database.fetchall("SELECT version FROM schema_migrations")
    } == set(range(1, 17))
    await database.close()


@pytest.mark.asyncio
async def test_legacy_m0_persistence_is_removed_after_migration(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await database.connect()
    async with database.transaction(immediate=True) as connection:
        for statement in _statements(
            (MIGRATIONS_DIR / "0001_conversation_m0.sql").read_text(encoding="utf-8")
        ):
            await connection.execute(statement)
        await connection.execute(
            "INSERT INTO conversations(account_id, conversation_id, character_id, "
            "stage_summary, context_version, created_at_utc, updated_at_utc) "
            "VALUES ('account', 'conversation', 'character', '', 'v1', '2026-01-01T00:00:00Z', "
            "'2026-01-01T00:00:00Z')"
        )
        await connection.execute(
            "INSERT INTO messages(message_id, account_id, conversation_id, sender_type, sender_id, "
            "text, images_json, client_msg_id, normalized_payload_hash, client_timestamp_utc, "
            "server_timestamp_utc, reply_to_message_id, trace_id) "
            "VALUES ('message', 'account', 'conversation', 'player', 'account', 'hello', '[]', "
            "'client', 'hash', NULL, '2026-01-01T00:00:00Z', NULL, 'trace')"
        )
        await connection.execute(
            "INSERT INTO messages(message_id, account_id, conversation_id, sender_type, sender_id, "
            "text, images_json, client_msg_id, normalized_payload_hash, client_timestamp_utc, "
            "server_timestamp_utc, reply_to_message_id, trace_id) "
            "VALUES ('character-message', 'account', 'conversation', 'character', 'character', "
            "'legacy reply', '[]', NULL, NULL, NULL, '2026-01-01T00:00:01Z', 'message', 'trace-2')"
        )
        await connection.execute(
            "INSERT INTO conversation_turns(turn_id, account_id, conversation_id, "
            "trigger_message_id, status, attempt_count, available_at_utc, lease_owner, "
            "lease_until_utc, last_error_code, created_at_utc, updated_at_utc, trace_id) "
            "VALUES ('turn', 'account', 'conversation', 'message', 'completed', 1, "
            "'2026-01-01T00:00:00Z', NULL, NULL, NULL, '2026-01-01T00:00:00Z', "
            "'2026-01-01T00:00:00Z', 'trace')"
        )
        await connection.execute(
            "INSERT INTO situation_proposals(proposal_id, turn_id, agent_id, status, utterance, "
            "actions_json, context_version, decision_code, created_at_utc, decided_at_utc) "
            "VALUES ('proposal', 'turn', 'old-agent', 'approved', 'legacy reply', '[]', 'v1', "
            "'approved', '2026-01-01T00:00:00Z', '2026-01-01T00:00:01Z')"
        )
        await connection.execute(
            "CREATE TABLE schema_migrations("
            "version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL)"
        )
        await connection.execute(
            "INSERT INTO schema_migrations(version, applied_at_utc) "
            "VALUES (1, '2026-01-01T00:00:00Z')"
        )

    await migrate(database)
    await assert_legacy_m0_persistence_removed(database)
    schema_version = await database.fetchone("SELECT value FROM meta WHERE key = 'schema_version'")
    assert schema_version["value"] == "16"
    migrated_message = await database.fetchone(
        "SELECT result_id, bubble_index FROM messages WHERE message_id = 'character-message'"
    )
    assert tuple(migrated_message) == (None, None)
    assert await database.fetchone("SELECT 1 FROM agent_results") is None
    for table in (
        "world_state",
        "character_states",
        "character_state_entries",
        "relationship_state",
        "relation_evidence",
        "conversation_participants",
        "conversation_tasks",
        "input_batches",
    ):
        row = await database.fetchone(f"SELECT COUNT(*) AS count FROM {table}")
        assert row["count"] == 0
    await database.close()


@pytest.mark.asyncio
async def test_0014_upgrade_rebuilds_reflection_runtime_tables(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await database.connect()
    async with database.transaction(immediate=True) as connection:
        await connection.execute(
            "CREATE TABLE schema_migrations("
            "version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL)"
        )
        for migration_file in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            version = int(migration_file.name[:4])
            if version > 14:
                continue
            for statement in _statements(migration_file.read_text(encoding="utf-8")):
                await connection.execute(statement)
            await connection.execute(
                "INSERT INTO schema_migrations(version, applied_at_utc) "
                "VALUES (?, '2026-09-19T12:00:00Z')",
                (version,),
            )
    await migrate(database)
    tables = {
        row["name"]
        for row in await database.fetchall(
            "SELECT name FROM sqlite_master WHERE type = 'table' AND name LIKE 'reflection%'"
        )
    }
    assert tables == {
        "reflection_graph_runs",
        "reflection_node_tasks",
        "reflection_artifacts",
        "reflection_graph_results",
    }
    assert await database.fetchall("PRAGMA foreign_key_check") == []
    await database.close()


@pytest.mark.asyncio
async def test_s5_schema_constraints_preserve_strangers_and_state_history(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await migrate(database)
    relationship_columns = {
        row["name"] for row in await database.fetchall("PRAGMA table_info(relationship_state)")
    }
    state_entry_columns = {
        row["name"] for row in await database.fetchall("PRAGMA table_info(character_state_entries)")
    }
    assert "initialized" not in relationship_columns
    assert {"affection", "trust", "attachment"} <= relationship_columns
    assert {"valid_from_utc", "retired_at_utc", "retirement_reason"}.isdisjoint(state_entry_columns)

    async with database.transaction(immediate=True) as connection:
        await connection.execute(
            "INSERT INTO relationship_state(account_id, observer_character_id, target_kind, "
            "target_id, relationship_type, state_version, updated_at_utc) "
            "VALUES ('account', 'xiaojin', 'account', 'account', 'stranger', 0, "
            "'2026-09-05T12:00:00Z')"
        )
        await connection.execute(
            "INSERT INTO relationship_state(account_id, observer_character_id, target_kind, "
            "target_id, relationship_type, affection, trust, attachment, state_version, "
            "updated_at_utc) VALUES ('account', 'acheng', 'account', 'account', 'acquaintance', "
            "25, 20, 0, "
            "1, '2026-09-05T12:00:00Z')"
        )
        await connection.execute(
            "INSERT INTO character_state_entries(entry_id, character_id, state_kind, value, "
            "source_kind, source_ref, state_version, recorded_at_utc, expires_at_utc) "
            "VALUES ('entry-1', 'xiaojin', 'activity', '整理画具', 'reflection', 'phase-1', 1, "
            "'2026-09-05T12:00:00Z', '2026-09-06T00:00:00Z')"
        )
        await connection.execute(
            "INSERT INTO relation_evidence(evidence_id, account_id, observer_character_id, "
            "target_kind, target_id, evidence_kind, source_kind, source_ref, occurred_at_utc, "
            "recorded_at_utc) VALUES ('evidence-1', 'account', 'xiaojin', 'account', 'account', "
            "'interaction', 'message', 'message-1', '2026-09-05T12:00:00Z', "
            "'2026-09-05T12:00:01Z')"
        )
        await connection.execute(
            "INSERT INTO relation_evidence(evidence_id, account_id, observer_character_id, "
            "target_kind, target_id, evidence_kind, source_kind, source_ref, occurred_at_utc, "
            "recorded_at_utc) VALUES ('evidence-friend', 'account', 'friend-subject', 'account', "
            "'account', 'support', 'message', 'message-friend', "
            "'2026-09-05T12:00:00Z', '2026-09-05T12:00:01Z')"
        )
        await connection.execute(
            "INSERT INTO relationship_state(account_id, observer_character_id, target_kind, "
            "target_id, relationship_type, affection, trust, attachment, "
            "friend_qualifying_evidence_id, state_version, updated_at_utc) "
            "VALUES ('account', 'friend-subject', 'account', 'account', 'friend', "
            "80, 75, 12, 'evidence-friend', 2, "
            "'2026-09-05T12:00:01Z')"
        )

    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await connection.execute(
                "INSERT INTO relationship_state(account_id, observer_character_id, target_kind, "
                "target_id, relationship_type, affection, trust, attachment, state_version, "
                "updated_at_utc) VALUES ('account', 'other', 'account', 'account', 'stranger', "
                "0, NULL, NULL, 0, '2026-09-05T12:00:00Z')"
            )

    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await connection.execute(
                "INSERT INTO relationship_state(account_id, observer_character_id, target_kind, "
                "target_id, relationship_type, affection, trust, attachment, state_version, "
                "updated_at_utc) VALUES ('account', 'invalid-score', 'account', 'account', "
                "'acquaintance', 101, 20, 0, 1, '2026-09-05T12:00:00Z')"
            )

    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await connection.execute(
                "INSERT INTO relationship_state(account_id, observer_character_id, target_kind, "
                "target_id, relationship_type, affection, trust, attachment, "
                "attitude_summary, attitude_source_refs_json, state_version, updated_at_utc) "
                "VALUES ('account', 'invalid-attitude-sources', 'account', 'account', "
                "'acquaintance', 50, 50, 0, '关系看法', '{}', 1, "
                "'2026-09-05T12:00:00Z')"
            )

    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await connection.execute(
                "INSERT INTO relationship_state(account_id, observer_character_id, target_kind, "
                "target_id, relationship_type, affection, trust, attachment, state_version, "
                "updated_at_utc) VALUES ('account', 'unqualified-friend', 'account', 'account', "
                "'friend', 80, 80, 10, 1, '2026-09-05T12:00:00Z')"
            )

    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await connection.execute(
                "INSERT INTO relationship_state(account_id, observer_character_id, target_kind, "
                "target_id, relationship_type, affection, trust, attachment, "
                "friend_qualifying_evidence_id, state_version, updated_at_utc) "
                "VALUES ('account', 'wrong-scope', 'account', 'account', 'acquaintance', "
                "80, 75, 12, 'evidence-friend', 2, "
                "'2026-09-05T12:00:01Z')"
            )

    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await connection.execute(
                "INSERT INTO relation_evidence(evidence_id, account_id, observer_character_id, "
                "target_kind, target_id, evidence_kind, source_kind, source_ref, "
                "occurred_at_utc, recorded_at_utc) "
                "VALUES ('evidence-2', 'account', 'xiaojin', 'account', 'account', "
                "'first_interaction', 'message', 'message-1', '2026-09-05T12:00:00Z', "
                "'2026-09-05T12:00:01Z')"
            )

    async with database.transaction(immediate=True) as connection:
        await connection.execute(
            "INSERT INTO character_state_entries(entry_id, character_id, state_kind, value, "
            "source_kind, source_ref, state_version, recorded_at_utc) "
            "VALUES ('entry-2', 'xiaojin', 'activity', '睡觉', 'reflection', 'phase-2', 2, "
            "'2026-09-05T13:00:00Z')"
        )
    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await connection.execute(
                "INSERT INTO character_state_entries(entry_id, character_id, state_kind, value, "
                "source_kind, source_ref, state_version, recorded_at_utc) "
                "VALUES ('entry-3', 'xiaojin', 'activity', '整理画具', 'reflection', 'phase-3', "
                "2, '2026-09-06T00:00:00Z')"
            )
    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await connection.execute(
                "INSERT INTO character_state_entries(entry_id, character_id, state_kind, value, "
                "source_kind, source_ref, state_version, recorded_at_utc) "
                "VALUES ('entry-4', 'xiaojin', 'activity', '重复来源', 'reflection', 'phase-1', "
                "3, '2026-09-06T00:00:00Z')"
            )

    stranger = await database.fetchone(
        "SELECT relationship_type, affection, trust, attachment FROM relationship_state "
        "WHERE observer_character_id = 'xiaojin'"
    )
    assert tuple(stranger) == ("stranger", None, None, None)
    await database.close()


@pytest.mark.asyncio
async def test_s5_migration_upgrades_schema_0006_without_rewriting_existing_state(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await database.connect()
    async with database.transaction(immediate=True) as connection:
        await connection.execute(
            "CREATE TABLE schema_migrations("
            "version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL)"
        )
        for migration_file in sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql")):
            version = int(migration_file.name[:4])
            if version > 6:
                continue
            for statement in _statements(migration_file.read_text(encoding="utf-8")):
                await connection.execute(statement)
            await connection.execute(
                "INSERT INTO schema_migrations(version, applied_at_utc) "
                "VALUES (?, '2026-09-05T12:00:00Z')",
                (version,),
            )
        await connection.execute(
            "INSERT INTO world_state(singleton_id, state_version, world_time_utc, status, phase, "
            "updated_at_utc) VALUES (1, 7, '2026-09-05T12:00:00Z', 'active', 'phase-a', "
            "'2026-09-05T12:00:00Z')"
        )
        await connection.execute(
            "INSERT INTO character_states(character_id, availability_status, reason_code, "
            "next_check_at_utc, state_version, updated_at_utc) VALUES ('xiaojin', 'available', "
            "NULL, NULL, 9, '2026-09-05T12:00:00Z')"
        )

    await migrate(database)

    world = await database.fetchone("SELECT state_version, phase FROM world_state")
    character = await database.fetchone(
        "SELECT availability_status, state_version FROM character_states "
        "WHERE character_id = 'xiaojin'"
    )
    assert tuple(world) == (7, "phase-a")
    assert tuple(character) == ("available", 9)
    assert await database.fetchone("SELECT 1 FROM relationship_state") is None
    assert await database.fetchone("SELECT 1 FROM relation_evidence") is None
    assert await database.fetchone("SELECT 1 FROM character_state_entries") is None
    schema_version = await database.fetchone("SELECT value FROM meta WHERE key = 'schema_version'")
    assert schema_version["value"] == "16"
    await database.close()


@pytest.mark.asyncio
async def test_cleanup_preserves_canonical_conversation_data(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await database.connect()
    async with database.transaction(immediate=True) as connection:
        await connection.execute(
            "CREATE TABLE schema_migrations("
            "version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL)"
        )
        for version, filename in (
            (1, "0001_conversation_m0.sql"),
            (2, "0002_agent_proposals.sql"),
            (3, "0003_conversation_runtime.sql"),
        ):
            for statement in _statements((MIGRATIONS_DIR / filename).read_text(encoding="utf-8")):
                await connection.execute(statement)
            await connection.execute(
                "INSERT INTO schema_migrations(version, applied_at_utc) "
                "VALUES (?, '2026-01-01T00:00:00Z')",
                (version,),
            )
        await connection.execute(
            "INSERT INTO conversations(account_id, conversation_id, character_id, stage_summary, "
            "context_version, created_at_utc, updated_at_utc, kind, status) "
            "VALUES ('account', 'conversation', 'character', '', 'v1', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', 'direct', 'active')"
        )
        await connection.execute(
            "INSERT INTO character_states(character_id, availability_status, state_version, "
            "updated_at_utc) VALUES ('character', 'available', 0, '2026-01-01T00:00:00Z')"
        )
        await connection.execute(
            "INSERT INTO conversation_participants(account_id, conversation_id, character_id, "
            "joined_at_utc) VALUES ('account', 'conversation', 'character', "
            "'2026-01-01T00:00:00Z')"
        )

    await migrate(database)
    await assert_legacy_m0_persistence_removed(database)
    conversation = await database.fetchone(
        "SELECT account_id, conversation_id, context_version, kind, status FROM conversations"
    )
    assert tuple(conversation) == ("account", "conversation", "v1", "direct", "active")
    assert (await database.fetchone("SELECT COUNT(*) AS count FROM conversation_participants"))[
        "count"
    ] == 1
    await database.close()


@pytest.mark.asyncio
async def test_runtime_migration_preserves_messages_but_discards_legacy_work_items(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await database.connect()
    async with database.transaction(immediate=True) as connection:
        for statement in _statements(
            (MIGRATIONS_DIR / "0001_conversation_m0.sql").read_text(encoding="utf-8")
        ):
            await connection.execute(statement)
        await connection.execute(
            "INSERT INTO conversations(account_id, conversation_id, character_id, "
            "stage_summary, context_version, created_at_utc, updated_at_utc) "
            "VALUES ('account', 'conversation', 'character', '', 'v1', "
            "'2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z')"
        )
        await connection.executemany(
            "INSERT INTO messages(message_id, account_id, conversation_id, sender_type, sender_id, "
            "text, images_json, client_msg_id, normalized_payload_hash, client_timestamp_utc, "
            "server_timestamp_utc, reply_to_message_id, trace_id) "
            "VALUES (?, 'account', 'conversation', 'player', 'account', ?, '[]', NULL, NULL, "
            "NULL, ?, NULL, ?)",
            [
                ("message-1", "first", "2026-01-01T00:00:00Z", "trace-1"),
                ("message-2", "second", "2026-01-01T00:00:01Z", "trace-2"),
                ("message-3", "third", "2026-01-01T00:00:02Z", "trace-3"),
            ],
        )
        await connection.executemany(
            "INSERT INTO conversation_turns(turn_id, account_id, conversation_id, "
            "trigger_message_id, status, attempt_count, available_at_utc, lease_owner, "
            "lease_until_utc, last_error_code, created_at_utc, updated_at_utc, trace_id) "
            "VALUES (?, 'account', 'conversation', ?, ?, ?, '2026-01-01T00:00:00Z', "
            "NULL, NULL, NULL, '2026-01-01T00:00:00Z', '2026-01-01T00:00:00Z', ?)",
            [
                ("turn-1", "message-1", "pending", 0, "trace-turn-1"),
                ("turn-2", "message-2", "retry_wait", 2, "trace-turn-2"),
            ],
        )
        await connection.execute(
            "CREATE TABLE schema_migrations("
            "version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL)"
        )
        await connection.execute(
            "INSERT INTO schema_migrations(version, applied_at_utc) "
            "VALUES (1, '2026-01-01T00:00:00Z')"
        )

    await migrate(database)
    await assert_legacy_m0_persistence_removed(database)

    tasks = await database.fetchall(
        "SELECT task_id, status, attempt_count, input_max_message_sequence FROM conversation_tasks"
    )
    assert tasks == []
    batches = await database.fetchall(
        "SELECT input_batch_id, status, task_id FROM input_batches ORDER BY first_message_sequence"
    )
    assert batches == []
    linked_messages = await database.fetchall(
        "SELECT message_id, input_batch_id, result_id, bubble_index "
        "FROM messages ORDER BY message_sequence"
    )
    assert [tuple(message) for message in linked_messages] == [
        ("message-1", None, None, None),
        ("message-2", None, None, None),
        ("message-3", None, None, None),
    ]
    await database.close()
