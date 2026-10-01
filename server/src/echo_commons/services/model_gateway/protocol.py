"""Provider-independent single-request Model Gateway contracts."""

from __future__ import annotations

from datetime import datetime
from enum import StrEnum
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field, model_validator

from echo_server.agents.contracts.refs import OutputContractRef
from echo_server.agents.contracts.run import UsageSummary


class ModelResponseKind(StrEnum):
    TERMINAL = "terminal"
    TOOL_CALL = "tool_call"
    NO_PROPOSAL = "no_proposal"
    INVALID = "invalid"


class PromptMessage(BaseModel):
    """Provider-neutral message projected by the Harness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    role: str
    content: str
    metadata: dict[str, object] = Field(default_factory=dict)


class ToolCall(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    name: str
    arguments: dict[str, object] = Field(default_factory=dict)


class ModelRequest(BaseModel):
    """One model request; it never represents a complete Agent Run."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: UUID
    trace_id: UUID
    agent_id: str
    model_profile: str
    model_entry_id: str | None = None
    attempt: int = Field(ge=1)
    step_index: int = Field(ge=1)
    messages: tuple[PromptMessage, ...] = ()
    output_contract: OutputContractRef | None = None
    # TEMPORARY COMPATIBILITY: provider adapters still pass the compact
    # schema string; the canonical field above is normalized first.
    output_schema: str | None = None
    allowed_tools: tuple[str, ...] = ()
    tool_definitions: tuple[dict[str, object], ...] = ()
    remaining_tool_calls: int = Field(default=0, ge=0)
    max_output_tokens: int | None = Field(default=None, ge=1)
    temperature: float | None = Field(default=None, ge=0, le=2)
    top_p: float | None = Field(default=None, gt=0, le=1)
    stream: bool = False
    deadline_utc: datetime | None = None

    @model_validator(mode="before")
    @classmethod
    def normalize_output_contract(cls, value: object) -> object:
        if not isinstance(value, dict):
            return value
        data = dict(value)
        contract = data.get("output_contract")
        schema = data.get("output_schema")
        if contract is None:
            if not isinstance(schema, str) or not schema:
                raise ValueError("model request requires output_contract")
            if schema.startswith("proposal.v1["):
                contract = OutputContractRef(kind="proposal", version="v1")
            elif "." not in schema:
                contract = OutputContractRef(kind=schema, version="legacy")
            else:
                contract = OutputContractRef.from_schema_id(schema)
            data["output_contract"] = contract
        elif isinstance(contract, str):
            data["output_contract"] = OutputContractRef.from_schema_id(contract)
            contract = data["output_contract"]
        elif isinstance(contract, dict):
            contract = OutputContractRef.model_validate(contract)
            data["output_contract"] = contract
        if not isinstance(schema, str) or not schema:
            data["output_schema"] = contract.schema_id
        return data

    @model_validator(mode="after")
    def output_schema_matches_contract(self) -> ModelRequest:
        if self.output_contract is None or self.output_schema is None:
            raise ValueError("model request requires output contract and schema")
        if (
            self.output_contract.version != "legacy"
            and self.output_contract.kind != "proposal"
            and self.output_schema != self.output_contract.schema_id
        ):
            raise ValueError("model request output schema does not match output contract")
        return self


class ModelResponse(BaseModel):
    """One provider response normalized for the Harness."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    kind: ModelResponseKind
    error_code: str | None = Field(default=None, min_length=1, max_length=120)
    output: dict[str, object] | None = None
    tool_calls: tuple[ToolCall, ...] = ()
    provider: str = "unknown"
    access_route: str = "unknown"
    model_vendor: str = "unknown"
    model: str = "unknown"
    usage_summary: UsageSummary = Field(default_factory=UsageSummary)
    finish_reason: str | None = None
    request_id: str | None = None
    latency_ms: int = Field(default=0, ge=0)
    ttft_ms: int | None = Field(default=None, ge=0)
    provider_attempt: int = Field(default=1, ge=1)
    retryable: bool = False

    @model_validator(mode="after")
    def validate_shape(self) -> ModelResponse:
        if self.kind is ModelResponseKind.TERMINAL and self.output is None:
            raise ValueError("terminal model response requires output")
        if self.kind is ModelResponseKind.TOOL_CALL and not self.tool_calls:
            raise ValueError("tool_call model response requires tool calls")
        return self

    @classmethod
    def terminal(cls, output: dict[str, object], **kwargs: object) -> ModelResponse:
        return cls(kind=ModelResponseKind.TERMINAL, output=output, **kwargs)

    @classmethod
    def tool_call(
        cls,
        name: str,
        arguments: dict[str, object] | None = None,
        *,
        call_id: str = "tool-call-1",
        **kwargs: object,
    ) -> ModelResponse:
        return cls(
            kind=ModelResponseKind.TOOL_CALL,
            tool_calls=(ToolCall(call_id=call_id, name=name, arguments=arguments or {}),),
            **kwargs,
        )

    @classmethod
    def no_proposal(cls, **kwargs: object) -> ModelResponse:
        return cls(kind=ModelResponseKind.NO_PROPOSAL, **kwargs)

    @classmethod
    def invalid(
        cls,
        *,
        error_code: str = "invalid_model_output",
        **kwargs: object,
    ) -> ModelResponse:
        return cls(kind=ModelResponseKind.INVALID, error_code=error_code, **kwargs)


class ModelGatewayError(RuntimeError):
    """Stable error raised by a Provider adapter."""

    code = "model_gateway_error"

    def __init__(
        self,
        message: str = "model gateway request failed",
        *,
        code: str | None = None,
        retryable: bool = True,
        status_code: int | None = None,
        provider_attempt: int = 1,
        retry_after_seconds: float | None = None,
    ):
        super().__init__(message)
        if code is not None:
            self.code = code
        self.retryable = retryable
        self.status_code = status_code
        self.provider_attempt = provider_attempt
        self.retry_after_seconds = retry_after_seconds


class ModelGateway(Protocol):
    async def generate(self, request: ModelRequest) -> ModelResponse:
        """Perform exactly one model request."""
