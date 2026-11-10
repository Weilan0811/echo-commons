from dataclasses import dataclass
from datetime import datetime
from enum import StrEnum
from typing import Protocol

from echo_commons.agents.contracts.recovery import TaskRecoveryDecision
from echo_commons.execution.observations import ExecutionObservation


class SchedulingLane(StrEnum):
    TURN = "turn"
    EXCHANGE = "exchange"
    BACKGROUND = "background"


@dataclass(frozen=True, slots=True)
class TaskCandidate:
    task_id: str
    task_kind: str
    available_at_utc: str
    created_at_utc: str
    required_scopes: tuple[tuple[str, ...], ...] = ()
    lane: SchedulingLane | None = None


@dataclass(frozen=True, slots=True)
class TaskOccupancy:
    task_id: str
    task_kind: str
    scopes: tuple[tuple[str, ...], ...]
    waiting_since: tuple[str, str, str] | None = None


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
    scheduling_lane: SchedulingLane | None = None


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
