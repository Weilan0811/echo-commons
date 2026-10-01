from __future__ import annotations

import json
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from support_faults import MutableClock

from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.domain.conversation import Conversation, ConversationKind, ConversationParticipant
from echo_server.domain.messages import SubmitMessageCommand
from echo_server.domain.state import (
    CharacterAvailabilityStatus,
    CharacterState,
    WorldState,
    WorldStatus,
)
from echo_server.runtime.application_runtime import (
    ApplicationRuntime,
    DatabaseUnavailableError,
    UnsupportedCapabilityError,
)
from echo_server.runtime.input_preparation import OfflineInputPreparation
from echo_server.store.database import Database

BASE_TIME = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def t2_runtime(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        worker_enabled=False,
        retry_backoff_seconds=0,
    )
    clock = MutableClock(BASE_TIME)
    runtime = ApplicationRuntime(
        Database(settings.database_path),
        StubCharacterAgent(),
        settings,
        clock=clock,
        worker_id="t2-test-worker",
    )
    await runtime.start()
    await seed_runtime_state(runtime, clock)
    yield runtime, clock
    if runtime.database.is_open:
        await runtime.stop()


async def seed_runtime_state(
    runtime: ApplicationRuntime,
    clock: MutableClock,
    *,
    character_id: str | None = None,
    conversation_id: str | None = None,
    character_status: CharacterAvailabilityStatus = CharacterAvailabilityStatus.AVAILABLE,
    world_status: WorldStatus = WorldStatus.ACTIVE,
) -> None:
    character = character_id or runtime.settings.default_character_id
    conversation = conversation_id or runtime.settings.default_conversation_id
    async with runtime.database.transaction(immediate=True) as connection:
        await runtime.world_states.save(
            WorldState(
                state_version=0,
                world_time_utc=clock.current,
                updated_at_utc=clock.current,
                status=world_status,
            ),
            connection=connection,
        )
        await runtime.character_states.save(
            CharacterState(
                character_id=character,
                availability_status=character_status,
                state_version=0,
                updated_at_utc=clock.current,
            ),
            connection=connection,
        )
        await runtime.participants.save(
            ConversationParticipant(
                conversation_id=conversation,
                character_id=character,
                joined_at_utc=clock.current,
            ),
            account_id=runtime.settings.account_id,
            connection=connection,
        )


def build_command(
    runtime: ApplicationRuntime,
    text: str,
    *,
    conversation_id: str | None = None,
) -> SubmitMessageCommand:
    return SubmitMessageCommand(
        account_id=runtime.settings.account_id,
        conversation_id=conversation_id or runtime.settings.default_conversation_id,
        player_text=text,
        images=(),
        client_msg_id=uuid4(),
        local_timestamp=BASE_TIME,
    )


async def submit(
    runtime: ApplicationRuntime,
    text: str = "hello",
    *,
    conversation_id: str | None = None,
) -> UUID:
    receipt = await runtime.submit_message(
        build_command(runtime, text, conversation_id=conversation_id)
    )
    return receipt.message_id


async def get_batch_for_message(runtime: ApplicationRuntime, message_id: UUID):
    row = await runtime.database.fetchone(
        "SELECT input_batch_id FROM messages WHERE message_id = ?",
        (str(message_id),),
    )
    assert row is not None
    batch = await runtime.input_batches.get(UUID(row["input_batch_id"]))
    assert batch is not None
    return batch


@pytest.mark.asyncio
async def test_t2_seals_due_batch_creates_task_and_freezes_boundaries(t2_runtime):
    runtime, clock = t2_runtime
    message_id = await submit(runtime, "hello")
    clock.current = BASE_TIME + timedelta(seconds=6)

    task = await runtime.prepare_next_task()

    assert task is not None
    assert task.status.value == "pending"
    assert task.input_max_message_sequence == task.context_max_message_sequence
    assert task.world_state_version == 0
    assert task.character_state_version == 0
    batch = await get_batch_for_message(runtime, message_id)
    assert batch.status.value == "assigned"
    assert batch.task_id == task.task_id
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM conversation_tasks"))[
        "count"
    ] == 1
    await runtime.flush_trace_outbox()
    trace_kinds = {
        row["kind"]
        for row in await runtime.database.fetchall(
            "SELECT kind FROM traces WHERE correlation_id = ?",
            (str(task.trace_id),),
        )
    }
    assert {"input_batch.sealed", "input_batch.assigned", "task.created"} <= trace_kinds


@pytest.mark.asyncio
async def test_t2_merges_the_earliest_waiting_batch_prefix(t2_runtime):
    runtime, clock = t2_runtime
    first_message_id = await submit(runtime, "first")
    clock.current = BASE_TIME + timedelta(seconds=6)
    second_message_id = await submit(runtime, "second")
    clock.current = BASE_TIME + timedelta(seconds=12)

    task = await runtime.prepare_next_task()

    assert task is not None
    first_batch = await get_batch_for_message(runtime, first_message_id)
    second_batch = await get_batch_for_message(runtime, second_message_id)
    assert first_batch.task_id == task.task_id
    assert second_batch.task_id == task.task_id
    assert first_batch.status.value == "assigned"
    assert second_batch.status.value == "assigned"
    assert task.input_max_message_sequence == second_batch.last_message_sequence


@pytest.mark.asyncio
async def test_t2_leaves_batch_waiting_when_eligibility_is_blocked(t2_runtime):
    runtime, clock = t2_runtime
    async with runtime.database.transaction(immediate=True) as connection:
        await runtime.character_states.save(
            CharacterState(
                character_id=runtime.settings.default_character_id,
                availability_status=CharacterAvailabilityStatus.BUSY,
                state_version=1,
                updated_at_utc=clock.current,
                reason_code="story_event",
            ),
            connection=connection,
        )
    message_id = await submit(runtime)
    clock.current = BASE_TIME + timedelta(seconds=6)

    task = await runtime.prepare_next_task()

    assert task is None
    batch = await get_batch_for_message(runtime, message_id)
    assert batch.status.value == "waiting"
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM conversation_tasks"))[
        "count"
    ] == 0
    await runtime.flush_trace_outbox()
    trace = await runtime.database.fetchone(
        "SELECT payload_json FROM traces WHERE kind = 'task.blocked' ORDER BY rowid DESC"
    )
    assert trace is not None
    payload = json.loads(trace["payload_json"])
    assert payload == {
        "decision_code": "character_busy",
        "error_code": "response_ineligible",
    }


@pytest.mark.asyncio
async def test_t2_rejects_group_conversation_without_mutating_batch(t2_runtime):
    runtime, clock = t2_runtime
    conversation = await runtime.runtime_conversations.get(
        runtime.settings.account_id,
        runtime.settings.default_conversation_id,
    )
    assert conversation is not None
    async with runtime.database.transaction(immediate=True) as connection:
        await runtime.runtime_conversations.save(
            replace(conversation, kind=ConversationKind.GROUP),
            connection=connection,
        )
    message_id = await submit(runtime)
    clock.current = BASE_TIME + timedelta(seconds=6)

    with pytest.raises(UnsupportedCapabilityError):
        await runtime.prepare_next_task()

    batch = await get_batch_for_message(runtime, message_id)
    assert batch.status.value == "collecting"
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM conversation_tasks"))[
        "count"
    ] == 0


@pytest.mark.asyncio
async def test_t2_respects_one_active_task_and_keeps_later_input_outside_boundary(t2_runtime):
    runtime, clock = t2_runtime
    first_message_id = await submit(runtime, "first")
    clock.current = BASE_TIME + timedelta(seconds=6)
    first_task = await runtime.prepare_next_task()
    assert first_task is not None
    first_batch = await get_batch_for_message(runtime, first_message_id)

    clock.current = BASE_TIME + timedelta(seconds=7)
    second_message_id = await submit(runtime, "later")
    clock.current = BASE_TIME + timedelta(seconds=13)
    second_task = await runtime.prepare_next_task()

    assert second_task is None
    second_batch = await get_batch_for_message(runtime, second_message_id)
    assert second_batch.status.value == "waiting"
    assert second_batch.task_id is None
    assert first_task.context_max_message_sequence == first_batch.last_message_sequence
    assert second_batch.first_message_sequence > first_task.context_max_message_sequence


@pytest.mark.asyncio
async def test_t2_capacity_assigns_only_a_contiguous_prefix(t2_runtime):
    runtime, clock = t2_runtime
    runtime.input_preparation = OfflineInputPreparation(max_messages=1)
    first_message_id = await submit(runtime, "first")
    clock.current = BASE_TIME + timedelta(seconds=6)
    second_message_id = await submit(runtime, "second")
    clock.current = BASE_TIME + timedelta(seconds=12)

    task = await runtime.prepare_next_task()

    assert task is not None
    first_batch = await get_batch_for_message(runtime, first_message_id)
    second_batch = await get_batch_for_message(runtime, second_message_id)
    assert first_batch.status.value == "assigned"
    assert first_batch.task_id == task.task_id
    assert second_batch.status.value == "waiting"
    assert second_batch.task_id is None
    assert task.input_max_message_sequence == first_batch.last_message_sequence


@pytest.mark.asyncio
async def test_t2_does_not_create_task_when_first_batch_exceeds_capacity(t2_runtime):
    runtime, clock = t2_runtime
    runtime.input_preparation = OfflineInputPreparation(max_characters=3)
    message_id = await submit(runtime, "too long")
    clock.current = BASE_TIME + timedelta(seconds=6)

    task = await runtime.prepare_next_task()

    assert task is None
    batch = await get_batch_for_message(runtime, message_id)
    assert batch.status.value == "waiting"
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM conversation_tasks"))[
        "count"
    ] == 0


@pytest.mark.asyncio
async def test_t2_isolates_conversations_when_preparing_tasks(t2_runtime):
    runtime, clock = t2_runtime
    other_conversation_id = "other-conversation"
    other_character_id = "other-character"
    other_conversation = Conversation(
        conversation_id=other_conversation_id,
        account_id=runtime.settings.account_id,
        kind=ConversationKind.DIRECT,
        created_at_utc=clock.current,
        updated_at_utc=clock.current,
    )
    async with runtime.database.transaction(immediate=True) as connection:
        await runtime.runtime_conversations.create(
            other_conversation,
            connection=connection,
        )
        await runtime.character_states.save(
            CharacterState(
                character_id=other_character_id,
                availability_status=CharacterAvailabilityStatus.AVAILABLE,
                state_version=0,
                updated_at_utc=clock.current,
            ),
            connection=connection,
        )
        await runtime.participants.save(
            ConversationParticipant(
                conversation_id=other_conversation_id,
                character_id=other_character_id,
                joined_at_utc=clock.current,
            ),
            account_id=runtime.settings.account_id,
            connection=connection,
        )
    default_message_id = await submit(runtime, "default")
    other_message_id = await submit(
        runtime,
        "other",
        conversation_id=other_conversation_id,
    )
    clock.current = BASE_TIME + timedelta(seconds=6)

    other_task = await runtime.prepare_next_task(conversation_id=other_conversation_id)
    default_task = await runtime.prepare_next_task()

    assert other_task is not None
    assert default_task is not None
    assert other_task.conversation_id == other_conversation_id
    assert default_task.conversation_id == runtime.settings.default_conversation_id
    assert (await get_batch_for_message(runtime, other_message_id)).task_id == other_task.task_id
    assert (
        await get_batch_for_message(runtime, default_message_id)
    ).task_id == default_task.task_id


@pytest.mark.asyncio
async def test_t2_rolls_back_task_and_batch_assignment_on_persistence_failure(
    t2_runtime, monkeypatch
):
    runtime, clock = t2_runtime
    message_id = await submit(runtime)
    clock.current = BASE_TIME + timedelta(seconds=6)

    async def fail_assign(*args, **kwargs):
        raise RuntimeError("assignment failed")

    monkeypatch.setattr(runtime.input_batches, "assign", fail_assign)

    with pytest.raises(DatabaseUnavailableError):
        await runtime.prepare_next_task()

    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM conversation_tasks"))[
        "count"
    ] == 0
    batch = await get_batch_for_message(runtime, message_id)
    assert batch.status.value == "collecting"
    await runtime.flush_trace_outbox()
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM traces WHERE kind = 'task.created'"
        )
    )["count"] == 0


@pytest.mark.asyncio
async def test_t2_can_prepare_a_persisted_batch_after_runtime_restart(t2_runtime):
    runtime, clock = t2_runtime
    await submit(runtime, "persist me")
    database_path = runtime.settings.database_path
    await runtime.stop()

    restarted_clock = MutableClock(BASE_TIME + timedelta(seconds=6))
    restarted = ApplicationRuntime(
        Database(database_path),
        StubCharacterAgent(),
        runtime.settings,
        clock=restarted_clock,
    )
    await restarted.start()
    try:
        task = await restarted.prepare_next_task()
        assert task is not None
        assert task.status.value == "pending"
        assert (
            await restarted.database.fetchone(
                "SELECT COUNT(*) AS count FROM input_batches WHERE status = 'assigned'"
            )
        )["count"] == 1
    finally:
        await restarted.stop()
