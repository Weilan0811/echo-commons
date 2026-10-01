from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest
import pytest_asyncio

from echo_commons.observability.trace import TraceQueryService, safe_trace_payload
from echo_commons.store.database import Database
from echo_commons.store.migrations import migrate
from echo_commons.store.trace_repository import TraceRepository

BASE_TIME = datetime(2026, 9, 20, 12, tzinfo=UTC)


@pytest_asyncio.fixture
async def trace_database(tmp_path):
    database = Database(str(tmp_path / "echo.sqlite3"))
    await migrate(database)
    yield database
    await database.close()


def test_safe_trace_payload_requires_registered_scalar_fields() -> None:
    payload = safe_trace_payload(
        "agent.completed",
        agent_id="character-agent",
        step_count=2,
    )

    assert payload == {"agent_id": "character-agent", "step_count": 2}

    with pytest.raises(ValueError, match="does not allow fields: prompt"):
        safe_trace_payload("agent.completed", prompt="private text")
    with pytest.raises(TypeError, match="must be a scalar"):
        safe_trace_payload("agent.completed", step_count=[2])


@pytest.mark.asyncio
async def test_trace_query_returns_materialized_events_by_correlation_and_entity(
    trace_database,
):
    repository = TraceRepository(trace_database)
    query = TraceQueryService(repository)
    correlation_id = uuid4()
    first_trace_id = uuid4()
    second_trace_id = uuid4()

    async with trace_database.transaction(immediate=True) as connection:
        await repository.enqueue(
            trace_id=first_trace_id,
            correlation_id=correlation_id,
            kind="task.created",
            entity_type="task",
            entity_id="task-1",
            payload=safe_trace_payload("task.created", context_version="context-v1"),
            created_at=BASE_TIME,
            connection=connection,
        )
        await repository.enqueue(
            trace_id=second_trace_id,
            correlation_id=correlation_id,
            kind="agent.completed",
            entity_type="task",
            entity_id="task-1",
            payload=safe_trace_payload("agent.completed", step_count=1),
            created_at=BASE_TIME + timedelta(seconds=1),
            connection=connection,
        )

    first_claim = await repository.claim_next(
        worker_id="trace-test",
        now_utc=BASE_TIME,
        lease_seconds=30,
    )
    assert first_claim is not None
    assert await repository.materialize(first_claim.trace_id, worker_id="trace-test")
    second_claim = await repository.claim_next(
        worker_id="trace-test",
        now_utc=BASE_TIME + timedelta(seconds=1),
        lease_seconds=30,
    )
    assert second_claim is not None
    assert await repository.materialize(second_claim.trace_id, worker_id="trace-test")

    by_correlation = await query.by_correlation(correlation_id)
    by_entity = await query.by_entity("task", "task-1")

    assert [record.kind for record in by_correlation] == [
        "task.created",
        "agent.completed",
    ]
    assert by_entity == by_correlation
    assert by_correlation[0].payload == {"context_version": "context-v1"}
