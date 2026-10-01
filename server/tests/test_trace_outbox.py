from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio
from support_faults import (
    FaultInjectingTraceRepository,
    FaultPlan,
    FaultPoint,
    MutableClock,
)

from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.domain.conversation import ConversationParticipant
from echo_server.domain.messages import SubmitMessageCommand
from echo_server.domain.state import CharacterAvailabilityStatus, CharacterState, WorldState
from echo_server.runtime.application_runtime import ApplicationRuntime
from echo_server.runtime.conversation_worker import ConversationWorker
from echo_server.store.database import Database
from echo_server.store.migrations import migrate
from echo_server.store.trace_repository import TraceRepository

BASE_TIME = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


@pytest_asyncio.fixture
async def trace_database(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await migrate(database)
    yield database
    await database.close()


@pytest.mark.asyncio
async def test_trace_outbox_materializes_once_and_deduplicates(trace_database):
    repository = TraceRepository(trace_database)
    trace_id = uuid4()
    kwargs = {
        "trace_id": trace_id,
        "correlation_id": uuid4(),
        "kind": "outbox.test",
        "entity_type": "test",
        "entity_id": "one",
        "payload": {"attempt_count": 1},
        "created_at": BASE_TIME,
    }
    async with trace_database.transaction(immediate=True) as connection:
        await repository.enqueue(**kwargs, connection=connection)
        await repository.enqueue(
            **{**kwargs, "payload": {"attempt_count": 2}}, connection=connection
        )

    assert (await trace_database.fetchone("SELECT COUNT(*) AS count FROM trace_outbox"))[
        "count"
    ] == 1
    claimed = await repository.claim_next(
        worker_id="trace-worker",
        now_utc=BASE_TIME,
        lease_seconds=30,
    )
    assert claimed is not None
    assert claimed.trace_id == trace_id
    assert claimed.status == "processing"
    assert claimed.attempt_count == 1
    assert await repository.materialize(trace_id, worker_id="trace-worker")
    assert not await repository.materialize(trace_id, worker_id="trace-worker")
    assert (await trace_database.fetchone("SELECT COUNT(*) AS count FROM trace_outbox"))[
        "count"
    ] == 0
    trace = await trace_database.fetchone(
        "SELECT payload_json FROM traces WHERE trace_id = ?", (str(trace_id),)
    )
    assert trace is not None
    assert trace["payload_json"] == '{"attempt_count":1}'


@pytest.mark.asyncio
async def test_trace_outbox_retries_then_retains_terminal_failure(trace_database):
    repository = TraceRepository(trace_database)
    trace_id = uuid4()
    async with trace_database.transaction(immediate=True) as connection:
        await repository.enqueue(
            trace_id=trace_id,
            correlation_id=uuid4(),
            kind="outbox.retry",
            entity_type="test",
            entity_id="retry",
            payload={},
            created_at=BASE_TIME,
            connection=connection,
        )

    first = await repository.claim_next(
        worker_id="trace-worker",
        now_utc=BASE_TIME,
        lease_seconds=1,
    )
    assert first is not None
    assert not await repository.retry(
        trace_id,
        worker_id="trace-worker",
        now_utc=BASE_TIME,
        retry_delay=0,
        max_attempts=2,
        error_code="delivery_failed",
    )
    second = await repository.claim_next(
        worker_id="trace-worker",
        now_utc=BASE_TIME,
        lease_seconds=1,
    )
    assert second is not None
    assert second.attempt_count == 2
    assert await repository.retry(
        trace_id,
        worker_id="trace-worker",
        now_utc=BASE_TIME,
        retry_delay=0,
        max_attempts=2,
        error_code="delivery_failed_again",
    )

    row = await trace_database.fetchone(
        "SELECT status, attempt_count, last_error_code FROM trace_outbox WHERE trace_id = ?",
        (str(trace_id),),
    )
    assert tuple(row) == ("failed", 2, "delivery_failed_again")
    assert (
        await repository.claim_next(
            worker_id="another-worker",
            now_utc=BASE_TIME,
            lease_seconds=1,
        )
        is None
    )


@pytest.mark.asyncio
async def test_trace_outbox_recovers_an_expired_lease(trace_database):
    repository = TraceRepository(trace_database)
    async with trace_database.transaction(immediate=True) as connection:
        await repository.enqueue(
            trace_id=uuid4(),
            correlation_id=uuid4(),
            kind="outbox.recovery",
            entity_type="test",
            entity_id="lease",
            payload={},
            created_at=BASE_TIME,
            connection=connection,
        )

    first = await repository.claim_next(
        worker_id="old-worker",
        now_utc=BASE_TIME,
        lease_seconds=1,
    )
    assert first is not None
    recovered = await repository.claim_next(
        worker_id="new-worker",
        now_utc=BASE_TIME + timedelta(seconds=2),
        lease_seconds=30,
    )
    assert recovered is not None
    assert recovered.attempt_count == 2
    assert recovered.lease_owner == "new-worker"


@pytest.mark.asyncio
async def test_runtime_start_recovers_trace_lease_after_restart(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        worker_enabled=False,
        trace_retry_backoff_seconds=0,
    )
    first = ApplicationRuntime(
        Database(settings.database_path),
        StubCharacterAgent(),
        settings,
        clock=MutableClock(BASE_TIME),
        worker_id="old-trace-worker",
    )
    await first.start()
    trace_id = uuid4()
    try:
        async with first.database.transaction(immediate=True) as connection:
            await first.traces.enqueue(
                trace_id=trace_id,
                correlation_id=uuid4(),
                kind="outbox.restart",
                entity_type="test",
                entity_id="restart",
                payload={},
                created_at=BASE_TIME,
                connection=connection,
            )
        claimed = await first.traces.claim_next(
            worker_id="old-trace-worker",
            now_utc=BASE_TIME,
            lease_seconds=1,
        )
        assert claimed is not None
    finally:
        await first.stop()

    restarted = ApplicationRuntime(
        Database(settings.database_path),
        StubCharacterAgent(),
        settings,
        clock=MutableClock(BASE_TIME + timedelta(seconds=2)),
        worker_id="new-trace-worker",
    )
    await restarted.start()
    try:
        row = await restarted.database.fetchone(
            "SELECT status, lease_owner FROM trace_outbox WHERE trace_id = ?",
            (str(trace_id),),
        )
        assert tuple(row) == ("pending", None)
        assert await restarted.flush_trace_outbox() == 1
        assert (
            await restarted.database.fetchone(
                "SELECT 1 FROM traces WHERE trace_id = ?", (str(trace_id),)
            )
        ) is not None
    finally:
        await restarted.stop()


@pytest.mark.asyncio
async def test_runtime_keeps_core_message_when_trace_delivery_fails_once(tmp_path):
    faults = FaultPlan()
    clock = MutableClock(BASE_TIME)
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        worker_enabled=False,
        trace_retry_backoff_seconds=0,
        trace_max_attempts=2,
    )
    runtime = ApplicationRuntime(
        Database(settings.database_path),
        StubCharacterAgent(),
        settings,
        clock=clock,
        worker_id="trace-runtime-worker",
    )
    await runtime.start()
    runtime.traces = FaultInjectingTraceRepository(TraceRepository(runtime.database), faults)
    try:
        receipt = await runtime.submit_message(
            SubmitMessageCommand(
                account_id=settings.account_id,
                conversation_id=settings.default_conversation_id,
                player_text="durable message",
                images=(),
                client_msg_id=uuid4(),
                local_timestamp=BASE_TIME,
            )
        )
        faults.fail_next(FaultPoint.TRACE_MATERIALIZE)
        assert await runtime.flush_trace_outbox() == 0
        assert (
            await runtime.database.fetchone(
                "SELECT 1 FROM messages WHERE message_id = ?", (str(receipt.message_id),)
            )
        ) is not None
        assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM traces"))[
            "count"
        ] == 0
        assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM trace_outbox"))[
            "count"
        ] == 2

        assert await runtime.flush_trace_outbox() == 2
        assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM traces"))[
            "count"
        ] == 2
        assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM trace_outbox"))[
            "count"
        ] == 0
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_worker_survives_trace_delivery_failure_after_task_commit(tmp_path):
    faults = FaultPlan()
    clock = MutableClock(BASE_TIME)
    settings = Settings(
        database_path=str(tmp_path / "echo.sqlite3"),
        worker_enabled=False,
        trace_retry_backoff_seconds=0,
    )
    runtime = ApplicationRuntime(
        Database(settings.database_path),
        StubCharacterAgent({"xiaojin": "reply"}),
        settings,
        clock=clock,
        worker_id="worker-with-trace-fault",
    )
    await runtime.start()
    runtime.traces = FaultInjectingTraceRepository(TraceRepository(runtime.database), faults)
    try:
        async with runtime.database.transaction(immediate=True) as connection:
            await runtime.world_states.save(
                WorldState(state_version=0, world_time_utc=BASE_TIME, updated_at_utc=BASE_TIME),
                connection=connection,
            )
            await runtime.character_states.save(
                CharacterState(
                    character_id=settings.default_character_id,
                    availability_status=CharacterAvailabilityStatus.AVAILABLE,
                    state_version=0,
                    updated_at_utc=BASE_TIME,
                ),
                connection=connection,
            )
            await runtime.participants.save(
                ConversationParticipant(
                    conversation_id=settings.default_conversation_id,
                    character_id=settings.default_character_id,
                    joined_at_utc=BASE_TIME,
                ),
                account_id=settings.account_id,
                connection=connection,
            )
        await runtime.submit_message(
            SubmitMessageCommand(
                account_id=settings.account_id,
                conversation_id=settings.default_conversation_id,
                player_text="worker message",
                images=(),
                client_msg_id=uuid4(),
                local_timestamp=BASE_TIME,
            )
        )
        assert await runtime.flush_trace_outbox() == 2

        clock.advance(timedelta(seconds=6))
        faults.fail_next(FaultPoint.TRACE_MATERIALIZE)
        worker = ConversationWorker(runtime)
        assert await worker.run_once()
        task = await runtime.database.fetchone("SELECT status FROM conversation_tasks")
        assert task is not None
        assert task["status"] == "completed"
        assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM trace_outbox"))[
            "count"
        ] > 0
        assert worker.failure is None

        await runtime.flush_trace_outbox()
        assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM trace_outbox"))[
            "count"
        ] == 0
        assert (
            await runtime.database.fetchone("SELECT 1 FROM traces WHERE kind = 'task.claimed'")
        ) is not None
    finally:
        await runtime.stop()


@pytest.mark.asyncio
async def test_runtime_event_enqueue_is_best_effort(tmp_path):
    faults = FaultPlan()
    settings = Settings(database_path=str(tmp_path / "echo.sqlite3"), worker_enabled=False)
    runtime = ApplicationRuntime(
        Database(settings.database_path),
        StubCharacterAgent(),
        settings,
        worker_id="event-worker",
    )
    await runtime.start()
    runtime.traces = FaultInjectingTraceRepository(TraceRepository(runtime.database), faults)
    try:
        faults.fail(FaultPoint.TRACE_ENQUEUE, times=2)
        await runtime._event(uuid4(), "agent.failed", "task", str(uuid4()), {})
        assert (await runtime.database.fetchone("SELECT COUNT(*) AS count FROM trace_outbox"))[
            "count"
        ] == 0
    finally:
        await runtime.stop()
