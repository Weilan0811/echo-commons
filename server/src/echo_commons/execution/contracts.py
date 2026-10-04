from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from echo_commons.agents.contracts.recovery import TaskRecoveryDecision
from echo_commons.execution.observations import ExecutionObservation


@dataclass(frozen=True, slots=True)
class TaskLease:
    task_id: str
    task_kind: str
    attempt: int
    generation: int
    owner: str
    expires_at_utc: datetime
    trace_id: str
    graph_execution_generation: int | None = None


class Disposition(StrEnum):
    COMPLETED = "completed"
    RECOVERY_REQUIRED = "recovery_required"
    HANDLED = "handled"
    IGNORED = "ignored"


@dataclass(frozen=True, slots=True)
class ExecutionOutcome:
    disposition: Disposition
    recovery: TaskRecoveryDecision | None = None
    observation: ExecutionObservation | None = None


class TaskQueue(Protocol):
    async def claim(self, owner: str, now: datetime) -> TaskLease | None: ...
    async def renew(self, lease: TaskLease, now: datetime) -> bool: ...
    async def recover(self, now: datetime) -> int: ...
    async def apply_recovery(
        self,
        lease: TaskLease,
        now: datetime,
        recovery: TaskRecoveryDecision,
        observation: ExecutionObservation | None = None,
    ) -> object: ...


class TaskHandler(Protocol):
    async def execute(self, lease: TaskLease) -> ExecutionOutcome: ...
