from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import UUID, uuid4

import pytest
import pytest_asyncio
from support_faults import MutableClock

from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.domain.messages import SubmitMessageCommand
from echo_server.runtime.application_runtime import (
    ApplicationRuntime,
    DatabaseUnavailableError,
    IdempotencyConflictError,
)
from echo_server.store.database import Database

BASE_TIME = datetime(2026, 9, 6, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def t1_runtime(tmp_path):
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
    )
    await runtime.start()
    yield runtime, clock
    if runtime.database.is_open:
        await runtime.stop()


def build_command(
    runtime: ApplicationRuntime,
    text: str,
    *,
    client_msg_id=None,
    local_timestamp: datetime | None = None,
) -> SubmitMessageCommand:
    return SubmitMessageCommand(
        account_id=runtime.settings.account_id,
        conversation_id=runtime.settings.default_conversation_id,
        player_text=text,
        images=(),
        client_msg_id=client_msg_id or uuid4(),
        local_timestamp=local_timestamp or BASE_TIME,
    )


async def submit(
    runtime: ApplicationRuntime,
    text: str = "hello",
    *,
    client_msg_id=None,
    local_timestamp: datetime | None = None,
):
    return await runtime.submit_message(
        build_command(
            runtime,
            text,
            client_msg_id=client_msg_id,
            local_timestamp=local_timestamp,
        )
    )


@pytest.mark.asyncio
async def test_t1_first_message_creates_collecting_batch(t1_runtime):
    runtime, clock = t1_runtime

    receipt = await submit(runtime, "first")

    message = await runtime.database.fetchone(
        "SELECT message_sequence, input_batch_id FROM messages WHERE message_id = ?",
        (str(receipt.message_id),),
    )
    assert message is not None
    assert message["message_sequence"] > 0
    assert message["input_batch_id"] is not None

    batch = await runtime.input_batches.get(UUID(message["input_batch_id"]))
    assert batch is not None
    assert batch.status.value == "collecting"
    assert batch.first_message_sequence == message["message_sequence"]
    assert batch.last_message_sequence == message["message_sequence"]
    assert batch.quiet_until_utc == clock.current + timedelta(seconds=6)

    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM conversation_tasks"))[
        "count"
    ] == 0

    await runtime.flush_trace_outbox()
    trace_kinds = {
        row["kind"]
        for row in await runtime.database.fetchall(
            "SELECT kind FROM traces WHERE correlation_id = ?",
            (str(receipt.trace_id),),
        )
    }
    assert {"input_batch.created", "message.accepted"} <= trace_kinds


@pytest.mark.asyncio
async def test_t1_messages_within_quiet_window_extend_same_batch(t1_runtime):
    runtime, clock = t1_runtime

    first = await submit(runtime, "first")
    clock.current = BASE_TIME + timedelta(seconds=3)
    second = await submit(runtime, "second")

    rows = await runtime.database.fetchall(
        "SELECT message_id, message_sequence, input_batch_id FROM messages "
        "WHERE message_id IN (?, ?) ORDER BY message_sequence",
        (str(first.message_id), str(second.message_id)),
    )
    assert len(rows) == 2
    assert rows[0]["input_batch_id"] == rows[1]["input_batch_id"]
    assert rows[0]["message_sequence"] < rows[1]["message_sequence"]

    batch = await runtime.input_batches.get(UUID(rows[0]["input_batch_id"]))
    assert batch is not None
    assert batch.quiet_until_utc == BASE_TIME + timedelta(seconds=9)
    assert batch.first_message_sequence == rows[0]["message_sequence"]
    assert batch.last_message_sequence == rows[1]["message_sequence"]


@pytest.mark.asyncio
async def test_t1_quiet_boundary_seals_old_batch_and_starts_new_batch(t1_runtime):
    runtime, clock = t1_runtime

    first = await submit(runtime, "first")
    clock.current = BASE_TIME + timedelta(seconds=6)
    second = await submit(runtime, "second")

    rows = await runtime.database.fetchall(
        "SELECT message_id, message_sequence, input_batch_id FROM messages "
        "WHERE message_id IN (?, ?) ORDER BY message_sequence",
        (str(first.message_id), str(second.message_id)),
    )
    assert rows[0]["input_batch_id"] != rows[1]["input_batch_id"]

    old_batch = await runtime.input_batches.get(UUID(rows[0]["input_batch_id"]))
    new_batch = await runtime.input_batches.get(UUID(rows[1]["input_batch_id"]))
    assert old_batch is not None
    assert new_batch is not None
    assert old_batch.status.value == "waiting"
    assert old_batch.sealed_at_utc == BASE_TIME + timedelta(seconds=6)
    assert new_batch.status.value == "collecting"
    assert new_batch.quiet_until_utc == BASE_TIME + timedelta(seconds=12)


@pytest.mark.asyncio
async def test_t1_idempotent_replay_does_not_extend_batch(t1_runtime):
    runtime, clock = t1_runtime
    client_msg_id = uuid4()
    local_timestamp = BASE_TIME

    first = await submit(
        runtime,
        "exact",
        client_msg_id=client_msg_id,
        local_timestamp=local_timestamp,
    )
    batch_before = await runtime.input_batches.get_collecting(
        runtime.settings.account_id,
        runtime.settings.default_conversation_id,
    )
    assert batch_before is not None

    clock.current = BASE_TIME + timedelta(seconds=2)
    replay = await submit(
        runtime,
        "exact",
        client_msg_id=client_msg_id,
        local_timestamp=local_timestamp,
    )
    batch_after = await runtime.input_batches.get_collecting(
        runtime.settings.account_id,
        runtime.settings.default_conversation_id,
    )

    assert replay == first
    assert batch_after == batch_before
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM messages"))["count"] == 1
    await runtime.flush_trace_outbox()
    assert (
        await runtime.database.fetchone(
            "SELECT COUNT(*) AS count FROM traces WHERE kind = 'message.idempotent_replay'"
        )
    )["count"] == 1


@pytest.mark.asyncio
async def test_t1_idempotency_conflict_does_not_mutate_batch(t1_runtime):
    runtime, _ = t1_runtime
    client_msg_id = uuid4()
    await submit(runtime, "original", client_msg_id=client_msg_id)
    before = await runtime.input_batches.get_collecting(
        runtime.settings.account_id,
        runtime.settings.default_conversation_id,
    )
    assert before is not None

    with pytest.raises(IdempotencyConflictError):
        await submit(runtime, "changed", client_msg_id=client_msg_id)

    after = await runtime.input_batches.get_collecting(
        runtime.settings.account_id,
        runtime.settings.default_conversation_id,
    )
    assert after == before
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM messages"))["count"] == 1


@pytest.mark.asyncio
async def test_t1_due_batch_sealing_is_persistent_and_wakes_runtime(t1_runtime):
    runtime, clock = t1_runtime
    wakeup = asyncio.Event()
    runtime.wakeup = wakeup
    await submit(runtime)
    wakeup.clear()

    clock.current = BASE_TIME + timedelta(seconds=6)
    assert await runtime.seal_due_input_batches() == 1
    assert wakeup.is_set()
    assert await runtime.seal_due_input_batches() == 0

    row = await runtime.database.fetchone("SELECT status FROM input_batches")
    assert row["status"] == "waiting"
    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM conversation_tasks"))[
        "count"
    ] == 0


@pytest.mark.asyncio
async def test_t1_transaction_rolls_back_batch_and_message_on_trace_failure(
    t1_runtime, monkeypatch
):
    runtime, _ = t1_runtime

    async def fail_trace(*args, **kwargs):
        raise RuntimeError("trace write failed")

    monkeypatch.setattr(runtime.traces, "enqueue", fail_trace)

    with pytest.raises(DatabaseUnavailableError):
        await submit(runtime)

    assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM messages"))["count"] == 0
    input_batches = await runtime.database.fetchone("SELECT COUNT(*) AS count FROM input_batches")
    assert input_batches["count"] == 0


@pytest.mark.asyncio
async def test_t1_batch_survives_runtime_restart(t1_runtime):
    runtime, _ = t1_runtime
    database_path = runtime.settings.database_path
    await submit(runtime, "persist me")
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
        assert await restarted.seal_due_input_batches() == 1
        row = await restarted.database.fetchone("SELECT status FROM input_batches")
        assert row["status"] == "waiting"
        message = await restarted.database.fetchone(
            "SELECT input_batch_id FROM messages WHERE text = ?", ("persist me",)
        )
        assert message["input_batch_id"]
    finally:
        await restarted.stop()
