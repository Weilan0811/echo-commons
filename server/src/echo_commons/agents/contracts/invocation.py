"""Immutable provider-neutral input for one Agent Run."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Annotated, Literal, TypeAlias
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_server.agents.contracts.context import ContextSnapshotV2
from echo_server.agents.contracts.reflection_context import ReflectionContext
from echo_server.agents.contracts.reflection_graph import GraphContextSnapshot, NodeInput
from echo_server.agents.contracts.refs import ContextInputRef, OutputContractRef

AgentContext: TypeAlias = ContextSnapshotV2 | ReflectionContext | GraphContextSnapshot | NodeInput


class InvocationPurpose(StrEnum):
    """Runtime-selected reason for invoking one Agent."""

    CONVERSATION_REPLY = "conversation_reply"
    REFLECTION = "reflection"


class InvocationIdentity(BaseModel):
    """Identity and purpose of one immutable Agent Run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: UUID = Field(default_factory=uuid4)
    agent_id: str = Field(min_length=1, max_length=200)
    agent_kind: str = Field(default="character", min_length=1, max_length=100)
    purpose: InvocationPurpose = InvocationPurpose.CONVERSATION_REPLY
    attempt: int = Field(default=1, ge=1)


class ConversationScope(BaseModel):
    """Scope for one normal character reply."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["conversation"] = "conversation"
    conversation_id: str = Field(min_length=1, max_length=200)
    character_id: str = Field(min_length=1, max_length=200)


class ReflectionNodeScope(BaseModel):
    """Scope for one node task in the Reflection graph."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: Literal["reflection_node"] = "reflection_node"
    graph_run_id: UUID
    node_task_id: UUID
    node_key: str = Field(min_length=1, max_length=200)
    character_id: str = Field(min_length=1, max_length=200)


InvocationScope: TypeAlias = Annotated[
    ConversationScope | ReflectionNodeScope,
    Field(discriminator="kind"),
]


class ExecutionPolicy(BaseModel):
    """Budgets and capabilities for one Agent Run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_tools: tuple[str, ...] = ()
    model_profile: str = Field(default="light", min_length=1, max_length=100)
    harness_version: str = Field(default="harness-v5", min_length=1, max_length=100)
    max_model_steps: int = Field(default=1, ge=1)
    max_model_requests: int | None = Field(default=None, ge=1)
    max_tool_calls: int = Field(default=0, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    deadline_utc: datetime | None = None


class Correlation(BaseModel):
    """Identifiers used to join an Agent Run to Runtime work and tracing."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    task_id: UUID | None = None
    trace_id: UUID


InvocationCorrelation = Correlation


class AgentInvocation(BaseModel):
    """The complete immutable input for one Echo-native Agent Run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    identity: InvocationIdentity
    scope: InvocationScope
    context: AgentContext
    context_input: ContextInputRef
    output_contract: OutputContractRef
    execution_policy: ExecutionPolicy = Field(default_factory=ExecutionPolicy)
    correlation: Correlation

    @model_validator(mode="after")
    def context_input_matches_snapshot(self) -> AgentInvocation:
        if isinstance(self.context, NodeInput):
            snapshot_id = self.context.snapshot_ref.snapshot_id
        else:
            snapshot_id = getattr(self.context, "snapshot_id", None)
            if snapshot_id is None:
                snapshot_id = getattr(self.context, "context_version", None)
        if snapshot_id is not None and self.context_input.snapshot_id != snapshot_id:
            raise ValueError("invocation context input snapshot_id does not match context snapshot")
        return self


__all__ = [
    "AgentContext",
    "AgentInvocation",
    "ConversationScope",
    "Correlation",
    "ExecutionPolicy",
    "InvocationCorrelation",
    "InvocationIdentity",
    "InvocationPurpose",
    "InvocationScope",
    "ReflectionNodeScope",
]
