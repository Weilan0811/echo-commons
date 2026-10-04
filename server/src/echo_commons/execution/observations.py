from typing import Literal

from pydantic import BaseModel, ConfigDict, Field

from echo_commons.agents.contracts.run import RepairObservation, UsageSummary
from echo_commons.execution.recovery import AppliedRecovery


class ExecutionObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    usage_summary: UsageSummary | None = None
    provider_attempt_count: int | None = Field(default=None, ge=0)
    repair_count: int = Field(default=0, ge=0)
    repairs: tuple[RepairObservation, ...] = ()
    exception_type: str | None = None


class ExecutionEventPayload(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    recovery: AppliedRecovery | None = None
    observation: ExecutionObservation | None = None
    repair_hint_used: str | None = None
    reason_code: str | None = None
    task_state: str | None = None


EventKind = Literal[
    "claimed",
    "invocation_started",
    "run_finished",
    "recovery_applied",
    "lifecycle_changed",
    "result_ignored",
    "completed",
]
