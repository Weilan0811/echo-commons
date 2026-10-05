from __future__ import annotations

from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny

from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.recovery import FailureCategory, FailureInfo
from echo_commons.agents.contracts.refs import OutputContractRef


class AgentRunStatus(StrEnum):
    COMPLETED = "completed"
    NO_PROPOSAL = "no_proposal"
    SUSPENDED = "suspended"
    CANCELLED = "cancelled"
    RETRYABLE = "retryable"
    FAILED = "failed"


class AgentStopReason(StrEnum):
    PROPOSAL_READY = "proposal_ready"
    NO_MOTIVATION = "no_motivation"
    BUDGET_EXHAUSTED = "budget_exhausted"
    DEADLINE_EXCEEDED = "deadline_exceeded"
    CANCELLED = "cancelled"
    INVALID_MODEL_OUTPUT = "invalid_model_output"
    TOOL_NOT_ALLOWED = "tool_not_allowed"
    TOOL_ERROR = "tool_error"
    MODEL_ERROR = "model_error"
    HARNESS_ERROR = "harness_error"


class UsageSummary(BaseModel):
    """Bounded model and tool usage counters; no prompt or output content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    model_request_count: int = Field(default=0, ge=0)
    tool_call_count: int = Field(default=0, ge=0)
    input_tokens: int = Field(default=0, ge=0)
    cache_read_tokens: int = Field(default=0, ge=0)
    cache_write_tokens: int = Field(default=0, ge=0)
    output_tokens: int = Field(default=0, ge=0)
    total_tokens: int = Field(default=0, ge=0)

    @property
    def cache_hit_ratio(self) -> float:
        denominator = self.input_tokens + self.cache_read_tokens
        return self.cache_read_tokens / denominator if denominator else 0.0

    def add(self, other: UsageSummary) -> UsageSummary:
        return UsageSummary(
            model_request_count=self.model_request_count + other.model_request_count,
            tool_call_count=self.tool_call_count + other.tool_call_count,
            input_tokens=self.input_tokens + other.input_tokens,
            cache_read_tokens=self.cache_read_tokens + other.cache_read_tokens,
            cache_write_tokens=self.cache_write_tokens + other.cache_write_tokens,
            output_tokens=self.output_tokens + other.output_tokens,
            total_tokens=self.total_tokens + other.total_tokens,
        )


class ToolActivity(BaseModel):
    """Safe summary of one local tool activity within an Agent Step."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    name: str
    ok: bool
    error_code: str | None = None
    duration_ms: int = Field(default=0, ge=0)
    progressed: bool | None = None
    new_item_count: int = Field(default=0, ge=0)
    no_progress_streak: int | None = Field(default=None, ge=0)


class AgentStep(BaseModel):
    """One model response and its local tool activity, without raw content."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    step_index: int = Field(ge=1)
    response_kind: str
    tool_activities: tuple[ToolActivity, ...] = ()
    usage_summary: UsageSummary = Field(default_factory=UsageSummary)
    duration_ms: int = Field(default=0, ge=0)
    diagnostic_codes: tuple[str, ...] = ()


class AgentOutput(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    contract: OutputContractRef
    payload: SerializeAsAny[BaseModel]


class RepairObservation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    code: str
    category: FailureCategory
    hint: str
    step_index: int = Field(ge=1)


class AgentRunResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: UUID
    agent_id: str
    agent_kind: str
    harness_version: str = "harness-v1"
    model_profile: str
    status: AgentRunStatus
    stop_reason: AgentStopReason
    output: AgentOutput | None = None
    usage_summary: UsageSummary = Field(default_factory=UsageSummary)
    steps: tuple[AgentStep, ...] = ()
    diagnostic_codes: tuple[str, ...] = ()
    recovery: FailureInfo | None = None
    repair_count: int = Field(default=0, ge=0)
    provider_attempt_count: int | None = Field(default=None, ge=0)
    repair_observations: tuple[RepairObservation, ...] = ()


class RunnableAgent(Protocol):
    async def run(self, invocation: AgentInvocation) -> AgentRunResult: ...
