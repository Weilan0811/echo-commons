from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol


@dataclass(frozen=True, slots=True)
class TaskLease:
    task_id: str
    task_kind: str
    attempt: int
    generation: int
    owner: str
    expires_at_utc: datetime
    trace_id: str


class Disposition(StrEnum):
    COMPLETED = "completed"
    RETRY = "retry"
    FAILED = "failed"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    disposition: Disposition
    error_code: str | None = None
    retry_after_seconds: float | None = None


class TaskQueue(Protocol):
    async def claim(self, owner: str, now: datetime) -> TaskLease | None: ...
    async def renew(self, lease: TaskLease, now: datetime) -> bool: ...
    async def recover(self, now: datetime) -> int: ...
    async def reschedule(
        self,
        lease: TaskLease,
        now: datetime,
        *,
        error_code: str,
        terminal: bool,
        retry_after_seconds: float | None = None,
    ) -> bool: ...


class TaskHandler(Protocol):
    async def execute(self, lease: TaskLease) -> ExecutionOutcome: ...
