from __future__ import annotations

import asyncio
from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
from support_agent_context import build_test_snapshot
from support_faults import (
    FaultInjectingDatabase,
    FaultInjectingTraceRepository,
    FaultPlan,
    FaultPoint,
    InjectedFault,
    MutableClock,
    PausableAgent,
    RestartableDatabase,
)

from echo_server.agents.contracts import (
    AgentInvocation,
    ContextInputRef,
    ConversationScope,
    Correlation,
    ExecutionPolicy,
    InvocationIdentity,
    OutputContractRef,
)
from echo_server.store.migrations import migrate
from echo_server.store.trace_repository import TraceRepository

BASE_TIME = datetime(2026, 9, 8, 12, 0, tzinfo=UTC)


def build_invocation() -> AgentInvocation:
    context = build_test_snapshot(now_utc=BASE_TIME)
    return AgentInvocation(
        identity=InvocationIdentity(agent_id="stub-character-agent"),
        scope=ConversationScope(
            conversation_id=context.conversation_id,
            character_id=context.character_id,
        ),
        context=context,
        context_input=ContextInputRef(
            snapshot_id=context.context_version,
            snapshot_schema_version=context.snapshot_version,
            snapshot_fingerprint=context.input_fingerprint,
        ),
        output_contract=OutputContractRef(kind="character_message", version="v2"),
        execution_policy=ExecutionPolicy(),
        correlation=Correlation(task_id=uuid4(), trace_id=uuid4()),
    )


def test_mutable_clock_advances_without_sleeping() -> None:
    clock = MutableClock(BASE_TIME)

    assert clock() == BASE_TIME
    assert clock.advance(timedelta(seconds=3)) == datetime(2026, 9, 8, 12, 0, 3, tzinfo=UTC)
    assert clock() == clock.current


def test_fault_plan_is_one_shot_and_counts_boundary_hits() -> None:
    faults = FaultPlan()
    faults.fail_next(FaultPoint.AGENT_RUN)

    with pytest.raises(InjectedFault) as failure:
        faults.hit(FaultPoint.AGENT_RUN)

    assert failure.value.point == FaultPoint.AGENT_RUN
    faults.hit(FaultPoint.AGENT_RUN)
    assert faults.hits(FaultPoint.AGENT_RUN) == 2
    assert faults.pending(FaultPoint.AGENT_RUN) == 0


@pytest.mark.asyncio
async def test_pausable_agent_blocks_records_and_releases_one_run() -> None:
    agent = PausableAgent()
    invocation = build_invocation()
    running = asyncio.create_task(agent.run(invocation))

    await agent.wait_until_started()
    assert agent.invocations == [invocation]
    assert not running.done()

    agent.release_call()
    result = await running

    assert result.invocation_id == invocation.identity.invocation_id
    assert agent.cancelled.is_set() is False


@pytest.mark.asyncio
async def test_fault_injecting_database_can_fail_connection(tmp_path) -> None:
    faults = FaultPlan()
    database = FaultInjectingDatabase(tmp_path / "echo.sqlite3", faults)
    faults.fail_next(FaultPoint.DATABASE_CONNECT)

    with pytest.raises(InjectedFault):
        await database.connect()

    assert database.is_open is False
    assert faults.hits(FaultPoint.DATABASE_CONNECT) == 1


@pytest.mark.asyncio
async def test_fault_injecting_database_forces_transaction_rollback(tmp_path) -> None:
    faults = FaultPlan()
    database = FaultInjectingDatabase(tmp_path / "echo.sqlite3", faults)
    await migrate(database)
    before_commit_hits = faults.hits(FaultPoint.DATABASE_TRANSACTION_BEFORE_COMMIT)
    faults.fail_next(FaultPoint.DATABASE_TRANSACTION_BEFORE_COMMIT)

    with pytest.raises(InjectedFault):
        async with database.transaction(immediate=True) as connection:
            await connection.execute(
                "CREATE TABLE injected_transaction_failure (id INTEGER PRIMARY KEY)"
            )

    assert (
        await database.fetchone(
            "SELECT 1 FROM sqlite_master WHERE type = 'table' "
            "AND name = 'injected_transaction_failure'"
        )
        is None
    )
    assert faults.hits(FaultPoint.DATABASE_TRANSACTION_BEFORE_COMMIT) == before_commit_hits + 1
    await database.close()


@pytest.mark.asyncio
async def test_fault_injecting_trace_can_fail_once_before_write(tmp_path) -> None:
    faults = FaultPlan()
    database = FaultInjectingDatabase(tmp_path / "echo.sqlite3", faults)
    await migrate(database)
    traces = FaultInjectingTraceRepository(TraceRepository(database), faults)
    trace_kwargs = {
        "trace_id": uuid4(),
        "correlation_id": uuid4(),
        "kind": "fault.test",
        "entity_type": "test",
        "entity_id": "fault-1",
        "payload": {},
        "created_at": BASE_TIME,
    }
    faults.fail_next(FaultPoint.TRACE_ENQUEUE)

    with pytest.raises(InjectedFault):
        async with database.transaction(immediate=True) as connection:
            await traces.enqueue(**trace_kwargs, connection=connection)
    assert (await database.fetchone("SELECT COUNT(*) AS count FROM traces"))["count"] == 0

    async with database.transaction(immediate=True) as connection:
        await traces.enqueue(**trace_kwargs, connection=connection)
    claimed = await traces.claim_next(
        worker_id="fault-test",
        now_utc=BASE_TIME,
        lease_seconds=30,
    )
    assert claimed is not None
    assert await traces.materialize(claimed.trace_id, worker_id="fault-test")
    assert (await database.fetchone("SELECT COUNT(*) AS count FROM traces"))["count"] == 1
    await database.close()


@pytest.mark.asyncio
async def test_restartable_database_reopens_the_same_durable_store(tmp_path) -> None:
    harness = RestartableDatabase(tmp_path / "echo.sqlite3")
    database = harness.open()
    await migrate(database)
    async with database.transaction(immediate=True) as connection:
        await connection.execute("CREATE TABLE restart_probe (value TEXT NOT NULL)")
        await connection.execute("INSERT INTO restart_probe(value) VALUES ('persisted')")

    reopened = await harness.reopen(database)
    try:
        await reopened.connect()
        row = await reopened.fetchone("SELECT value FROM restart_probe")
        assert row is not None
        assert row["value"] == "persisted"
    finally:
        await reopened.close()
