"""Reusable fault-injection primitives for Runtime reliability tests.

These helpers stay under ``tests/`` so fault switches cannot be enabled in a
packaged service by configuration. They provide deterministic control over
time, Agent execution, database transactions, Trace writes, and database
reopen scenarios without adding production-only branches to Runtime code.
"""

from __future__ import annotations

import asyncio
from collections import Counter, deque
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from dataclasses import dataclass, field
from datetime import datetime, timedelta
from pathlib import Path
from typing import Any

import aiosqlite

from echo_server.agents.contracts import AgentInvocation, AgentRunResult, RunnableAgent
from echo_server.agents.stubs import StubCharacterAgent
from echo_server.store.database import Database
from echo_server.store.trace_repository import TraceRepository


class FaultPoint:
    """Stable names for failure boundaries used by the test harness."""

    AGENT_RUN = "agent.run"
    DATABASE_CONNECT = "database.connect"
    DATABASE_EXECUTE = "database.execute"
    DATABASE_TRANSACTION_BEFORE = "database.transaction.before"
    DATABASE_TRANSACTION_AFTER_BEGIN = "database.transaction.after_begin"
    DATABASE_TRANSACTION_BEFORE_COMMIT = "database.transaction.before_commit"
    TRACE_ENQUEUE = "trace.enqueue"
    TRACE_MATERIALIZE = "trace.materialize"


class InjectedFault(RuntimeError):
    """Default exception raised by a scheduled fault."""

    def __init__(self, point: str) -> None:
        self.point = point
        super().__init__(f"injected fault at {point}")


class FaultPlan:
    """One-shot or repeated deterministic failures with hit accounting."""

    def __init__(self) -> None:
        self._scheduled: dict[str, deque[Exception]] = {}
        self._hits: Counter[str] = Counter()

    def fail_next(self, point: str, error: Exception | None = None) -> None:
        """Raise ``error`` the next time ``point`` is hit."""

        name = _point_name(point)
        self._scheduled.setdefault(name, deque()).append(error or InjectedFault(name))

    def fail(self, point: str, *, times: int = 1) -> None:
        """Raise a fresh ``InjectedFault`` at ``point`` ``times`` times."""

        if times < 1:
            raise ValueError("times must be positive")
        for _ in range(times):
            self.fail_next(point)

    def hit(self, point: str) -> None:
        """Record a boundary hit and raise its next scheduled failure."""

        name = _point_name(point)
        self._hits[name] += 1
        pending = self._scheduled.get(name)
        if not pending:
            return
        error = pending.popleft()
        if not pending:
            del self._scheduled[name]
        raise error

    def hits(self, point: str) -> int:
        return self._hits[_point_name(point)]

    def pending(self, point: str) -> int:
        return len(self._scheduled.get(_point_name(point), ()))


@dataclass
class MutableClock:
    """Callable clock that can advance without sleeping."""

    current: datetime

    def __call__(self) -> datetime:
        return self.current

    def advance(self, delta: timedelta) -> datetime:
        self.current += delta
        return self.current


class PausableAgent:
    """Agent fixture that pauses at the model boundary until released."""

    def __init__(
        self,
        delegate: RunnableAgent | None = None,
        *,
        faults: FaultPlan | None = None,
        initially_released: bool = False,
    ) -> None:
        self._delegate = delegate or StubCharacterAgent()
        self._faults = faults
        self.agent_id = getattr(self._delegate, "agent_id", "pausable-agent")
        self.agent_kind = getattr(self._delegate, "agent_kind", "character")
        self.model_profile = getattr(self._delegate, "model_profile", "stub")
        self.harness_version = getattr(self._delegate, "harness_version", "stub-v1")
        self.started = asyncio.Event()
        self.release = asyncio.Event()
        self.cancelled = asyncio.Event()
        self.invocations: list[AgentInvocation] = []
        if initially_released:
            self.release.set()

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        self.invocations.append(invocation)
        self.started.set()
        if self._faults is not None:
            self._faults.hit(FaultPoint.AGENT_RUN)
        try:
            await self.release.wait()
        except asyncio.CancelledError:
            self.cancelled.set()
            raise
        return await self._delegate.run(invocation)

    async def wait_until_started(self, timeout: float = 1.0) -> None:
        await asyncio.wait_for(self.started.wait(), timeout=timeout)

    def release_call(self) -> None:
        self.release.set()

    def reset_gate(self) -> None:
        self.started.clear()
        self.release.clear()
        self.cancelled.clear()


class FaultInjectingDatabase(Database):
    """Database test double with failures at connection and transaction edges."""

    def __init__(self, path: str | Path, faults: FaultPlan | None = None) -> None:
        super().__init__(path)
        self.faults = faults or FaultPlan()

    async def connect(self) -> None:
        self.faults.hit(FaultPoint.DATABASE_CONNECT)
        await super().connect()

    async def execute(
        self,
        sql: str,
        parameters: tuple[object, ...] = (),
    ) -> aiosqlite.Cursor:
        self.faults.hit(FaultPoint.DATABASE_EXECUTE)
        return await super().execute(sql, parameters)

    @asynccontextmanager
    async def transaction(self, *, immediate: bool = False) -> AsyncIterator[aiosqlite.Connection]:
        self.faults.hit(FaultPoint.DATABASE_TRANSACTION_BEFORE)
        async with super().transaction(immediate=immediate) as connection:
            self.faults.hit(FaultPoint.DATABASE_TRANSACTION_AFTER_BEGIN)
            yield connection
            self.faults.hit(FaultPoint.DATABASE_TRANSACTION_BEFORE_COMMIT)


class FaultInjectingTraceRepository:
    """TraceRepository decorator with separate enqueue and delivery faults."""

    def __init__(self, delegate: TraceRepository, faults: FaultPlan) -> None:
        self._delegate = delegate
        self._faults = faults

    async def enqueue(self, **kwargs: Any) -> None:
        self._faults.hit(FaultPoint.TRACE_ENQUEUE)
        await self._delegate.enqueue(**kwargs)

    async def recover_expired(self, now_utc: datetime, **kwargs: Any) -> int:
        return await self._delegate.recover_expired(now_utc, **kwargs)

    async def claim_next(self, **kwargs: Any) -> Any:
        return await self._delegate.claim_next(**kwargs)

    async def materialize(self, trace_id: Any, **kwargs: Any) -> bool:
        self._faults.hit(FaultPoint.TRACE_MATERIALIZE)
        return await self._delegate.materialize(trace_id, **kwargs)

    async def retry(self, trace_id: Any, **kwargs: Any) -> bool:
        return await self._delegate.retry(trace_id, **kwargs)


@dataclass(slots=True)
class RestartableDatabase:
    """Open and reopen the same durable database path for restart tests."""

    path: str | Path
    faults: FaultPlan = field(default_factory=FaultPlan)

    def __post_init__(self) -> None:
        self.path = Path(self.path)

    def open(self) -> FaultInjectingDatabase:
        return FaultInjectingDatabase(self.path, self.faults)

    async def reopen(self, database: Database) -> FaultInjectingDatabase:
        if database.is_open:
            await database.close()
        return self.open()


def _point_name(point: str) -> str:
    return point


__all__ = [
    "FaultInjectingDatabase",
    "FaultInjectingTraceRepository",
    "FaultPlan",
    "FaultPoint",
    "InjectedFault",
    "MutableClock",
    "PausableAgent",
    "RestartableDatabase",
]
