from __future__ import annotations

from datetime import UTC, datetime, timedelta
from uuid import uuid4

import pytest

from echo_server.runtime.dispatcher import (
    TaskClaimScope,
    TaskDispatcher,
    TaskDisposition,
    TaskExecutionResult,
    TaskHandlerRegistry,
    TaskLease,
)

NOW = datetime(2026, 9, 9, 12, 0, tzinfo=UTC)


def make_lease(task_kind: str = "opaque.task") -> TaskLease:
    return TaskLease(
        task_id=uuid4(),
        task_kind=task_kind,
        correlation_id=uuid4(),
        scope_key="opaque-scope",
        attempt_count=1,
        lease_generation=1,
        lease_owner="dispatcher-worker",
        lease_until_utc=NOW + timedelta(seconds=30),
        payload={"not": "conversation-specific"},
    )


class FakeStore:
    def __init__(self, lease: TaskLease | None) -> None:
        self.lease = lease
        self.recovered_at: datetime | None = None
        self.reschedules: list[tuple[TaskLease, str, bool]] = []

    async def recover_expired(self, now_utc: datetime) -> int:
        self.recovered_at = now_utc
        return 2

    async def claim_next(self, *, worker_id: str, now_utc: datetime, scope=None):
        assert worker_id == "dispatcher-worker"
        assert scope == TaskClaimScope(account_id="account", scope_key="scope")
        lease, self.lease = self.lease, None
        return lease

    async def reschedule(self, lease: TaskLease, *, error_code: str, terminal: bool = False):
        self.reschedules.append((lease, error_code, terminal))


class RecordingHandler:
    task_kind = "opaque.task"

    def __init__(self, result: TaskExecutionResult | None = None, error: Exception | None = None):
        self.result = result or TaskExecutionResult(TaskDisposition.COMMITTED)
        self.error = error
        self.payload = None

    async def execute(self, lease: TaskLease) -> TaskExecutionResult:
        self.payload = lease.payload
        if self.error is not None:
            raise self.error
        return self.result


@pytest.mark.asyncio
async def test_dispatcher_routes_opaque_lease_to_registered_handler() -> None:
    lease = make_lease()
    store = FakeStore(lease)
    handler = RecordingHandler()
    registry = TaskHandlerRegistry()
    registry.register(handler)
    dispatcher = TaskDispatcher(
        store,
        registry,
        worker_id="dispatcher-worker",
        clock=lambda: NOW,
    )

    assert await dispatcher.recover_expired() == 2
    assert store.recovered_at == NOW
    assert await dispatcher.dispatch_once(
        scope=TaskClaimScope(account_id="account", scope_key="scope")
    )
    assert handler.payload == {"not": "conversation-specific"}
    assert store.reschedules == []


@pytest.mark.asyncio
async def test_dispatcher_reschedules_handler_requested_retry() -> None:
    lease = make_lease()
    store = FakeStore(lease)
    registry = TaskHandlerRegistry()
    registry.register(
        RecordingHandler(TaskExecutionResult(TaskDisposition.RETRY, error_code="provider_busy"))
    )
    dispatcher = TaskDispatcher(
        store,
        registry,
        worker_id="dispatcher-worker",
        clock=lambda: NOW,
    )

    assert await dispatcher.dispatch_once(
        scope=TaskClaimScope(account_id="account", scope_key="scope")
    )
    assert [(code, terminal) for _, code, terminal in store.reschedules] == [
        ("provider_busy", False)
    ]


@pytest.mark.asyncio
async def test_dispatcher_fences_handler_failure_and_unknown_kind() -> None:
    lease = make_lease()
    store = FakeStore(lease)
    registry = TaskHandlerRegistry()
    dispatcher = TaskDispatcher(
        store,
        registry,
        worker_id="dispatcher-worker",
        clock=lambda: NOW,
    )

    assert await dispatcher.dispatch_once(
        scope=TaskClaimScope(account_id="account", scope_key="scope")
    )
    assert [(code, terminal) for _, code, terminal in store.reschedules] == [
        ("task_handler_not_registered", True)
    ]

    store = FakeStore(make_lease())
    failing_registry = TaskHandlerRegistry()
    failing_registry.register(RecordingHandler(error=RuntimeError("provider_down")))
    dispatcher = TaskDispatcher(
        store,
        failing_registry,
        worker_id="dispatcher-worker",
        clock=lambda: NOW,
    )
    assert await dispatcher.dispatch_once(
        scope=TaskClaimScope(account_id="account", scope_key="scope")
    )
    assert [(code, terminal) for _, code, terminal in store.reschedules] == [
        ("runtimeerror", False)
    ]


def test_registry_rejects_duplicate_task_kinds() -> None:
    registry = TaskHandlerRegistry()
    registry.register(RecordingHandler())
    with pytest.raises(ValueError, match="already registered"):
        registry.register(RecordingHandler())
