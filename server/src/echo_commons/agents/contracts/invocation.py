from datetime import datetime
from enum import StrEnum
from uuid import UUID, uuid4

from pydantic import BaseModel, ConfigDict, Field, SerializeAsAny, model_validator

from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.refs import ContextInputRef, OutputContractRef


class InvocationPurpose(StrEnum):
    ACTIVITY_TURN = "activity_turn"
    ACTIVITY_REPLY = "activity_reply"
    ACTIVITY_EXPRESSION = "activity_expression"
    CONVERSATION_REPLY = "conversation_reply"
    REFLECTION = "reflection"


class InvocationIdentity(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    invocation_id: UUID = Field(default_factory=uuid4)
    agent_id: str = Field(min_length=1)
    agent_kind: str = "character"
    purpose: InvocationPurpose
    attempt: int = Field(ge=1)


class InvocationScope(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    community_id: str = Field(min_length=1)
    character_id: str = Field(min_length=1)
    task_id: str = Field(min_length=1)
    source_kind: str = Field(min_length=1)
    source_id: str = Field(min_length=1)


class DraftFeedback(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    draft: dict[str, object]
    feedback: str = Field(min_length=1)


class ExecutionPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    allowed_tools: tuple[str, ...] = ()
    model_profile: str = Field(min_length=1)
    harness_version: str = "harness-v1"
    max_model_steps: int = Field(default=8, ge=1)
    max_model_requests: int = Field(default=8, ge=1)
    max_tool_calls: int = Field(default=8, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=1)
    max_content_chars: int | None = Field(default=None, ge=1)
    max_input_chars: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    deadline_utc: datetime | None = None
    output_instructions: str = ""
    repair_hint: str | None = None
    revision_history: tuple[DraftFeedback, ...] = ()


class Correlation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    task_id: str
    trace_id: UUID


class AgentInvocation(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    identity: InvocationIdentity
    scope: InvocationScope
    context: SerializeAsAny[InvocationInput]
    context_input: ContextInputRef
    output_contract: OutputContractRef
    execution_policy: ExecutionPolicy
    correlation: Correlation

    @model_validator(mode="after")
    def consistent_scope(self):
        if (self.scope.community_id, self.scope.character_id) != (
            self.context.scope.community_id,
            self.context.scope.character_id,
        ):
            raise ValueError("invocation scope does not match snapshot")
        if self.context_input.snapshot_id != self.context.snapshot_id:
            raise ValueError("invocation input does not match snapshot")
        if self.context_input.snapshot_schema_version != self.context.schema_version:
            raise ValueError("invocation input schema does not match snapshot")
        if self.scope.task_id != self.correlation.task_id:
            raise ValueError("invocation task does not match correlation")
        if self.output_contract not in self.context.action_space.output_contracts:
            raise ValueError("output contract exceeds snapshot action space")
        if not set(self.execution_policy.allowed_tools).issubset(self.context.action_space.tools):
            raise ValueError("tools exceed snapshot action space")
        return self
