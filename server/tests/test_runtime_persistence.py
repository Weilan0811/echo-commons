from __future__ import annotations

import sqlite3
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio

from echo_server.domain.conversation import Conversation, ConversationKind, ConversationParticipant
from echo_server.domain.input_batch import InputBatch
from echo_server.domain.messages import Message
from echo_server.domain.result import AgentResult
from echo_server.domain.state import CharacterAvailabilityStatus, CharacterState, WorldState
from echo_server.domain.task import ConversationTask
from echo_server.store.database import Database
from echo_server.store.migrations import migrate
from echo_server.store.runtime_repositories import (
    AgentResultRepository,
    CharacterStateRepository,
    ConversationParticipantRepository,
    ConversationTaskRepository,
    InputBatchRepository,
    RuntimeConversationRepository,
    RuntimeMessageRepository,
    WorldStateRepository,
)

BASE_TIME = datetime(2026, 9, 5, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def database(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await migrate(database)
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_s2_5_schema_is_created_empty_from_a_fresh_database(database):
    await migrate(database)
    rows = await database.fetchall("SELECT name FROM sqlite_master WHERE type = 'table'")
    tables = {row["name"] for row in rows}

    assert {
        "world_state",
        "character_states",
        "conversation_participants",
        "conversation_tasks",
        "input_batches",
        "agent_results",
        "trace_outbox",
        "memory_search_documents",
        "memory_search_fts",
    } <= tables
    assert {
        row["version"] for row in await database.fetchall("SELECT version FROM schema_migrations")
    } == set(range(1, 17))

    assert await WorldStateRepository(database).get() is None
    assert await database.fetchall("SELECT * FROM character_states") == []
    assert await database.fetchall("SELECT * FROM conversation_participants") == []
    assert await database.fetchall("SELECT * FROM conversation_tasks") == []
    assert await database.fetchall("SELECT * FROM input_batches") == []
    assert await database.fetchall("SELECT * FROM agent_results") == []

    columns = await database.fetchall("PRAGMA table_info(messages)")
    assert {row["name"] for row in columns} >= {
        "input_batch_id",
        "result_id",
        "bubble_index",
    }
    task_columns = await database.fetchall("PRAGMA table_info(conversation_tasks)")
    assert "lease_generation" in {row["name"] for row in task_columns}
    assert await database.fetchall("PRAGMA foreign_key_check") == []


@pytest.mark.asyncio
async def test_state_repositories_apply_compare_and_set_versions(database):
    world_repository = WorldStateRepository(database)
    world = WorldState(state_version=0, world_time_utc=BASE_TIME, updated_at_utc=BASE_TIME)
    async with database.transaction(immediate=True) as connection:
        await world_repository.save(world, connection=connection)
    advanced_world = world.advance(
        state_version=world.state_version + 1,
        world_time_utc=world.world_time_utc + timedelta(seconds=1),
        updated_at_utc=world.updated_at_utc + timedelta(seconds=1),
    )
    async with database.transaction(immediate=True) as connection:
        await world_repository.save(
            advanced_world,
            expected_version=world.state_version,
            connection=connection,
        )
    assert await world_repository.get() == advanced_world
    with pytest.raises(RuntimeError):
        async with database.transaction(immediate=True) as connection:
            await world_repository.save(
                advanced_world,
                expected_version=world.state_version,
                connection=connection,
            )

    character_repository = CharacterStateRepository(database)
    original_character = CharacterState(
        character_id="xiaojin",
        availability_status=CharacterAvailabilityStatus.AVAILABLE,
        state_version=0,
        updated_at_utc=BASE_TIME,
    )
    async with database.transaction(immediate=True) as connection:
        await character_repository.save(original_character, connection=connection)
    updated_character = original_character.update(
        availability_status=CharacterAvailabilityStatus.BUSY,
        state_version=1,
        updated_at_utc=BASE_TIME + timedelta(seconds=1),
        reason_code="story_event",
    )
    async with database.transaction(immediate=True) as connection:
        await character_repository.save(
            updated_character,
            expected_version=original_character.state_version,
            connection=connection,
        )
    assert await character_repository.get("xiaojin") == updated_character


@pytest.mark.asyncio
async def test_runtime_repositories_round_trip_all_runtime_entities(database):
    account_id = "account-1"
    conversation_id = "conversation-1"
    character_id = "xiaojin"
    conversation = Conversation(
        conversation_id=conversation_id,
        account_id=account_id,
        kind=ConversationKind.DIRECT,
        created_at_utc=BASE_TIME,
        updated_at_utc=BASE_TIME,
    )
    character_state = CharacterState(
        character_id=character_id,
        availability_status=CharacterAvailabilityStatus.AVAILABLE,
        state_version=0,
        updated_at_utc=BASE_TIME,
    )
    batch_id = uuid4()
    task_id = uuid4()
    result_id = uuid4()
    player_message_id = uuid4()
    trace_id = uuid4()
    invocation_id = uuid4()

    conversation_repository = RuntimeConversationRepository(database)
    character_repository = CharacterStateRepository(database)
    participant_repository = ConversationParticipantRepository(database)
    message_repository = RuntimeMessageRepository(database)
    batch_repository = InputBatchRepository(database)
    task_repository = ConversationTaskRepository(database)
    result_repository = AgentResultRepository(database)

    async with database.transaction(immediate=True) as connection:
        await character_repository.save(character_state, connection=connection)
        await conversation_repository.create(
            conversation,
            connection=connection,
        )
        await participant_repository.save(
            ConversationParticipant(
                conversation_id=conversation_id,
                character_id=character_id,
                joined_at_utc=BASE_TIME,
            ),
            account_id=account_id,
            connection=connection,
        )

        batch = InputBatch.start(
            input_batch_id=batch_id,
            account_id=account_id,
            conversation_id=conversation_id,
            now_utc=BASE_TIME,
        )
        await batch_repository.create(batch, connection=connection)

        player = Message.player(
            message_sequence=0,
            message_id=player_message_id,
            account_id=account_id,
            conversation_id=conversation_id,
            sender_id=account_id,
            text="hello",
            images=(),
            client_msg_id=uuid4(),
            client_timestamp_utc=BASE_TIME,
            server_timestamp_utc=BASE_TIME,
            input_batch_id=batch_id,
            reply_to_message_id=None,
            trace_id=trace_id,
        )
        stored_player = await message_repository.insert(
            player,
            normalized_payload_hash="hash",
            connection=connection,
        )
        batch = await batch_repository.append_message(
            batch_id,
            message_sequence=stored_player.message_sequence,
            now_utc=BASE_TIME,
            connection=connection,
        )
        batch = await batch_repository.seal(
            batch_id,
            now_utc=BASE_TIME + timedelta(seconds=6),
            connection=connection,
        )

        task = ConversationTask.create(
            task_id=task_id,
            account_id=account_id,
            conversation_id=conversation_id,
            character_id=character_id,
            input_max_message_sequence=stored_player.message_sequence,
            context_max_message_sequence=stored_player.message_sequence,
            world_state_version=0,
            character_state_version=0,
            context_version="0",
            trace_id=trace_id,
            now_utc=BASE_TIME + timedelta(seconds=7),
        )
        await task_repository.create(task, connection=connection)
        batch = await batch_repository.assign(
            batch_id,
            task_id=task_id,
            now_utc=BASE_TIME + timedelta(seconds=7),
            connection=connection,
        )

    assert batch.task_id == task_id

    claimed = await task_repository.claim_next(
        worker_id="worker-1",
        now_utc=BASE_TIME + timedelta(seconds=8),
        lease_seconds=30,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    assert claimed is not None
    assert claimed.task_id == task_id
    assert claimed.attempt_count == 1
    assert claimed.lease_generation == 1

    result = AgentResult(
        result_id=result_id,
        task_id=task_id,
        attempt_no=1,
        agent_id="character-agent",
        agent_kind="character",
        invocation_id=invocation_id,
        result_kind="character_message",
        schema_version="v1",
        context_version="0",
        payload_json='{"utterance":"hi"}',
        created_at_utc=BASE_TIME + timedelta(seconds=9),
    )
    approved = result.approve(decided_at_utc=BASE_TIME + timedelta(seconds=10))

    async with database.transaction(immediate=True) as connection:
        await result_repository.insert(result, connection=connection)
        await result_repository.save_decision(approved, connection=connection)
        character_message = Message.character(
            message_sequence=0,
            message_id=uuid4(),
            account_id=account_id,
            conversation_id=conversation_id,
            character_id=character_id,
            text="hi",
            server_timestamp_utc=BASE_TIME + timedelta(seconds=10),
            result_id=result_id,
            bubble_index=0,
            reply_to_message_id=player_message_id,
            trace_id=trace_id,
        )
        stored_character = await message_repository.insert(
            character_message,
            connection=connection,
        )
        await message_repository.insert(
            Message.character(
                message_sequence=0,
                message_id=uuid4(),
                account_id=account_id,
                conversation_id=conversation_id,
                character_id=character_id,
                text="second bubble",
                server_timestamp_utc=BASE_TIME + timedelta(seconds=10),
                result_id=result_id,
                bubble_index=1,
                reply_to_message_id=player_message_id,
                trace_id=trace_id,
            ),
            connection=connection,
        )
        await batch_repository.cover(
            batch_id,
            now_utc=BASE_TIME + timedelta(seconds=10),
            connection=connection,
        )
        await task_repository.complete(
            task_id,
            worker_id="worker-1",
            now_utc=BASE_TIME + timedelta(seconds=10),
            connection=connection,
        )

    assert await conversation_repository.get(account_id, conversation_id) == conversation
    assert await character_repository.get(character_id) == character_state
    assert await participant_repository.list_active(account_id, conversation_id)
    assert await result_repository.get(result_id) == approved
    messages = await message_repository.list_conversation(account_id, conversation_id)
    assert [message.text for message in messages] == ["hello", "hi", "second bubble"]
    assert stored_character.result_id == result_id
    assert stored_character.bubble_index == 0
    assert (await batch_repository.get(batch_id)).is_terminal
    assert (await task_repository.get(task_id)).is_terminal


@pytest.mark.asyncio
async def test_task_claim_recovery_and_retry_preserve_the_lease_invariant(database):
    account_id = "account-1"
    conversation_id = "conversation-1"
    character_id = "xiaojin"
    task_id = uuid4()

    async with database.transaction(immediate=True) as connection:
        await CharacterStateRepository(database).save(
            CharacterState(
                character_id=character_id,
                availability_status=CharacterAvailabilityStatus.AVAILABLE,
                state_version=0,
                updated_at_utc=BASE_TIME,
            ),
            connection=connection,
        )
        await RuntimeConversationRepository(database).create(
            Conversation(
                conversation_id=conversation_id,
                account_id=account_id,
                kind=ConversationKind.DIRECT,
                created_at_utc=BASE_TIME,
                updated_at_utc=BASE_TIME,
            ),
            connection=connection,
        )
        await ConversationTaskRepository(database).create(
            ConversationTask.create(
                task_id=task_id,
                account_id=account_id,
                conversation_id=conversation_id,
                character_id=character_id,
                input_max_message_sequence=1,
                context_max_message_sequence=1,
                world_state_version=0,
                character_state_version=0,
                context_version="0",
                trace_id=uuid4(),
                now_utc=BASE_TIME,
            ),
            connection=connection,
        )

    repository = ConversationTaskRepository(database)
    claimed = await repository.claim_next(
        worker_id="worker-1",
        now_utc=BASE_TIME,
        lease_seconds=5,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    assert claimed is not None
    assert claimed.lease_generation == 1
    renewed = await repository.renew_lease(
        task_id,
        worker_id="worker-1",
        now_utc=BASE_TIME + timedelta(seconds=1),
        lease_seconds=5,
        attempt_count=claimed.attempt_count,
        lease_generation=claimed.lease_generation,
    )
    assert renewed is not None
    assert renewed.lease_until_utc == BASE_TIME + timedelta(seconds=6)
    assert (
        await repository.renew_lease(
            task_id,
            worker_id="worker-1",
            now_utc=BASE_TIME + timedelta(seconds=2),
            lease_seconds=5,
            attempt_count=claimed.attempt_count,
            lease_generation=claimed.lease_generation - 1,
        )
        is None
    )
    assert (
        await repository.claim_next(
            worker_id="worker-2",
            now_utc=BASE_TIME + timedelta(seconds=1),
            lease_seconds=5,
            account_id=account_id,
            conversation_id=conversation_id,
        )
        is None
    )

    async with database.transaction(immediate=True) as connection:
        recovered_count = await repository.recover_expired(
            BASE_TIME + timedelta(seconds=6), connection=connection
        )
    assert recovered_count == 1
    reclaimed = await repository.claim_next(
        worker_id="worker-2",
        now_utc=BASE_TIME + timedelta(seconds=6),
        lease_seconds=5,
        account_id=account_id,
        conversation_id=conversation_id,
    )
    assert reclaimed is not None
    assert reclaimed.attempt_count == 2
    assert reclaimed.lease_generation == 2
    async with database.transaction(immediate=True) as connection:
        completed = await repository.complete(
            task_id,
            worker_id="worker-2",
            now_utc=BASE_TIME + timedelta(seconds=6),
            connection=connection,
        )
    assert completed.is_terminal


@pytest.mark.asyncio
async def test_database_constraints_prevent_duplicate_collecting_batches_and_bubbles(database):
    account_id = "account-1"
    conversation_id = "conversation-1"
    character_id = "xiaojin"
    batch_repository = InputBatchRepository(database)
    message_repository = RuntimeMessageRepository(database)

    async with database.transaction(immediate=True) as connection:
        await CharacterStateRepository(database).save(
            CharacterState(
                character_id=character_id,
                availability_status=CharacterAvailabilityStatus.AVAILABLE,
                state_version=0,
                updated_at_utc=BASE_TIME,
            ),
            connection=connection,
        )
        await RuntimeConversationRepository(database).create(
            Conversation(
                conversation_id=conversation_id,
                account_id=account_id,
                kind=ConversationKind.DIRECT,
                created_at_utc=BASE_TIME,
                updated_at_utc=BASE_TIME,
            ),
            connection=connection,
        )
        await batch_repository.create(
            InputBatch.start(
                input_batch_id=uuid4(),
                account_id=account_id,
                conversation_id=conversation_id,
                now_utc=BASE_TIME,
            ),
            connection=connection,
        )

    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await batch_repository.create(
                InputBatch.start(
                    input_batch_id=uuid4(),
                    account_id=account_id,
                    conversation_id=conversation_id,
                    now_utc=BASE_TIME,
                ),
                connection=connection,
            )

    task_id = uuid4()
    result_id = uuid4()
    player_id = uuid4()
    task_repository = ConversationTaskRepository(database)
    result_repository = AgentResultRepository(database)
    first_task = ConversationTask.create(
        task_id=task_id,
        account_id=account_id,
        conversation_id=conversation_id,
        character_id=character_id,
        input_max_message_sequence=1,
        context_max_message_sequence=1,
        world_state_version=0,
        character_state_version=0,
        context_version="0",
        trace_id=uuid4(),
        now_utc=BASE_TIME,
    )
    result = AgentResult(
        result_id=result_id,
        task_id=task_id,
        attempt_no=1,
        agent_id="agent",
        agent_kind="character",
        invocation_id=uuid4(),
        result_kind="character_message",
        schema_version="v1",
        context_version="0",
        payload_json='{"utterance":"hi"}',
        created_at_utc=BASE_TIME,
    )
    async with database.transaction(immediate=True) as connection:
        await task_repository.create(first_task, connection=connection)
        await result_repository.insert(result, connection=connection)
        await result_repository.save_decision(
            result.approve(decided_at_utc=BASE_TIME + timedelta(seconds=1)),
            connection=connection,
        )
        collecting_batch = await batch_repository.get_collecting(
            account_id, conversation_id, connection=connection
        )
        assert collecting_batch is not None
        await message_repository.insert(
            Message.player(
                message_sequence=0,
                message_id=player_id,
                account_id=account_id,
                conversation_id=conversation_id,
                sender_id=account_id,
                text="hello",
                images=(),
                client_msg_id=uuid4(),
                client_timestamp_utc=BASE_TIME,
                server_timestamp_utc=BASE_TIME,
                input_batch_id=collecting_batch.input_batch_id,
                reply_to_message_id=None,
                trace_id=uuid4(),
            ),
            normalized_payload_hash="hash",
            connection=connection,
        )
        await message_repository.insert(
            Message.character(
                message_sequence=0,
                message_id=uuid4(),
                account_id=account_id,
                conversation_id=conversation_id,
                character_id=character_id,
                text="first",
                server_timestamp_utc=BASE_TIME,
                result_id=result_id,
                bubble_index=0,
                reply_to_message_id=player_id,
                trace_id=uuid4(),
            ),
            connection=connection,
        )

    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await task_repository.create(
                ConversationTask.create(
                    task_id=uuid4(),
                    account_id=account_id,
                    conversation_id=conversation_id,
                    character_id=character_id,
                    input_max_message_sequence=1,
                    context_max_message_sequence=1,
                    world_state_version=0,
                    character_state_version=0,
                    context_version="0",
                    trace_id=uuid4(),
                    now_utc=BASE_TIME,
                ),
                connection=connection,
            )

    second_result = AgentResult(
        result_id=uuid4(),
        task_id=task_id,
        attempt_no=2,
        agent_id="agent",
        agent_kind="character",
        invocation_id=uuid4(),
        result_kind="character_message",
        schema_version="v1",
        context_version="0",
        payload_json='{"utterance":"second"}',
        created_at_utc=BASE_TIME,
    )
    async with database.transaction(immediate=True) as connection:
        await result_repository.insert(second_result, connection=connection)
    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await result_repository.save_decision(
                second_result.approve(decided_at_utc=BASE_TIME + timedelta(seconds=1)),
                connection=connection,
            )

    with pytest.raises(sqlite3.IntegrityError):
        async with database.transaction(immediate=True) as connection:
            await message_repository.insert(
                Message.character(
                    message_sequence=0,
                    message_id=uuid4(),
                    account_id=account_id,
                    conversation_id=conversation_id,
                    character_id=character_id,
                    text="duplicate",
                    server_timestamp_utc=BASE_TIME,
                    result_id=result_id,
                    bubble_index=0,
                    reply_to_message_id=player_id,
                    trace_id=uuid4(),
                ),
                connection=connection,
            )
