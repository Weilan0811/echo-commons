"""Agent Run output, usage, and diagnostic contracts."""

from __future__ import annotations

from enum import StrEnum
from typing import Annotated, Literal, Protocol, TypeAlias
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_server.agents.contracts.invocation import AgentInvocation
from echo_server.agents.contracts.proposals import (
    CHARACTER_MESSAGE_OUTPUT_SCHEMA,
    REFLECTION_NODE_OUTPUT_SCHEMA,
    InvocationOrigin,
    ProposalEnvelope,
    ProposalKind,
)
from echo_server.agents.contracts.recovery import FailureInfo
from echo_server.agents.contracts.reflection import ReflectionNodeAction
from echo_server.agents.contracts.refs import OutputContractRef


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


class ProposalOutput(BaseModel):
    """The conversation branch of a terminal Agent Run output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["proposal"] = "proposal"
    contract: OutputContractRef
    proposal: ProposalEnvelope

    @model_validator(mode="after")
    def contract_matches_proposal(self) -> ProposalOutput:
        if self.proposal.kind is not ProposalKind.CHARACTER_MESSAGE:
            raise ValueError("Agent Run Proposal output only supports character_message")
        expected = CHARACTER_MESSAGE_OUTPUT_SCHEMA
        if self.contract.schema_id != expected:
            raise ValueError("Proposal output contract does not match proposal kind")
        return self


class ReflectionNodeOutput(BaseModel):
    """The reflection-node branch of a terminal Agent Run output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["reflection_node"] = "reflection_node"
    contract: OutputContractRef
    action: ReflectionNodeAction

    @model_validator(mode="after")
    def contract_matches_action(self) -> ReflectionNodeOutput:
        if self.contract.schema_id != REFLECTION_NODE_OUTPUT_SCHEMA:
            raise ValueError("unsupported reflection node output contract")
        return self


AgentOutput: TypeAlias = Annotated[
    ProposalOutput | ReflectionNodeOutput,
    Field(discriminator="kind"),
]


class AgentRunResult(BaseModel):
    """Terminal result with exactly one typed output branch or no output."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: UUID
    agent_id: str
    agent_kind: str
    harness_version: str
    model_profile: str
    status: AgentRunStatus
    stop_reason: AgentStopReason
    step_count: int = Field(default=0, ge=0)
    steps: tuple[AgentStep, ...] = ()
    output: AgentOutput | None = None
    usage_summary: UsageSummary = Field(default_factory=UsageSummary)
    repair_count: int = Field(default=0, ge=0)
    diagnostic_codes: tuple[str, ...] = ()
    recovery: FailureInfo | None = None

    @model_validator(mode="after")
    def output_matches_status(self) -> AgentRunResult:
        if self.step_count != len(self.steps):
            raise ValueError("Agent Run step_count does not match steps")
        if self.status is AgentRunStatus.COMPLETED and self.output is None:
            raise ValueError("completed Agent Run requires output")
        if self.status is AgentRunStatus.NO_PROPOSAL and self.output is not None:
            raise ValueError("no_proposal Agent Run must not contain output")
        if (
            self.status in {AgentRunStatus.COMPLETED, AgentRunStatus.NO_PROPOSAL}
            and self.recovery is not None
        ):
            raise ValueError("successful Agent Run must not contain recovery information")
        if isinstance(self.output, ProposalOutput):
            if not isinstance(self.output.proposal.origin, InvocationOrigin):
                raise ValueError("Proposal output requires invocation origin")
            if self.output.proposal.origin.invocation_id != self.invocation_id:
                raise ValueError("Proposal output invocation does not match Agent Run")
        return self


class RunnableAgent(Protocol):
    """Runtime-facing protocol for the Echo-native Agent Run boundary."""

    agent_id: str
    agent_kind: str

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        """Execute a full internal Agent Loop and return a terminal result."""
