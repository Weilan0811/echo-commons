"""Stable contracts for durable task ownership and handler dispatch."""

from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID


class TaskDisposition(StrEnum):
    """Outcome visible to the generic dispatcher after handler execution."""

    COMMITTED = "committed"
    STALE = "stale"
    DEFERRED = "deferred"
    RETRY = "retry"
    TERMINAL_FAILURE = "terminal_failure"


@dataclass(frozen=True, slots=True)
class TaskClaimScope:
    """Opaque scheduler filters; concrete stores interpret their scope keys."""

    account_id: str | None = None
    scope_key: str | None = None


@dataclass(frozen=True, slots=True)
class TaskLease:
    """Immutable fencing identity handed from a persistent store to a handler."""

    task_id: UUID
    task_kind: str
    correlation_id: UUID
    scope_key: str
    attempt_count: int
    lease_generation: int
    lease_owner: str
    lease_until_utc: datetime
    payload: object


@dataclass(frozen=True, slots=True)
class TaskExecutionResult:
    """A handler result; only retry dispositions trigger generic state changes."""

    disposition: TaskDisposition
    error_code: str | None = None


class PersistentTaskStore(Protocol):
    """Persistence port for a durable task queue."""

    async def recover_expired(self, now_utc: datetime) -> int:
        """Recover expired leases before a new dispatch cycle."""

    async def claim_next(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        scope: TaskClaimScope | None = None,
    ) -> TaskLease | None:
        """Atomically claim the next task and return its fencing identity."""

    async def reschedule(
        self,
        lease: TaskLease,
        *,
        error_code: str,
        terminal: bool = False,
    ) -> None:
        """Release a still-owned lease into retry or terminal failure."""


class TaskHandler(Protocol):
    """One task-kind implementation resolved by the registry."""

    task_kind: str

    async def execute(self, lease: TaskLease) -> TaskExecutionResult:
        """Execute outside a database write transaction."""


__all__ = [
    "PersistentTaskStore",
    "TaskClaimScope",
    "TaskDisposition",
    "TaskExecutionResult",
    "TaskHandler",
    "TaskLease",
]
