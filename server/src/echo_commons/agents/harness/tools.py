from __future__ import annotations

from collections.abc import Iterable
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from echo_commons.agents.contracts.context import SourceVersion
from echo_commons.agents.contracts.invocation import AgentInvocation, InvocationScope
from echo_commons.agents.contracts.refs import ContextInputRef
from echo_commons.agents.harness.progress import ToolProgressExtractor
from echo_commons.infrastructure.models.protocol import ToolCall


class ToolExecutionError(RuntimeError):
    code = "tool_execution_error"


class ToolAuthorizationError(ToolExecutionError):
    code = "tool_not_allowed"


class ToolReadPolicy(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    observed_at_utc: datetime
    conversation_id: str | None = None
    upper_sequence: int | None = Field(default=None, ge=0)
    source_versions: tuple[SourceVersion, ...] = ()


class ToolContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    invocation_id: UUID
    agent_id: str
    call_id: str
    tool_name: str
    scope: InvocationScope
    context_input: ContextInputRef
    read_policy: ToolReadPolicy


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    name: str
    ok: bool
    output: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None


class ReadOnlyTool(Protocol):
    name: str
    definition: dict[str, object]

    async def invoke(self, arguments: dict[str, object], context: ToolContext) -> ToolResult:
        """Read from an injected snapshot-backed capability."""


@dataclass(frozen=True, slots=True)
class ToolRegistration:
    tool: ReadOnlyTool
    progress_extractor: ToolProgressExtractor | None = None
    no_progress_limit: int | None = None

    @property
    def name(self) -> str:
        return self.tool.name

    def __post_init__(self) -> None:
        if self.no_progress_limit is not None and self.no_progress_limit < 1:
            raise ValueError("no_progress_limit must be positive")


class ToolRegistry:
    def __init__(self, tools: Iterable[ReadOnlyTool | ToolRegistration] = ()) -> None:
        self._tools: dict[str, ToolRegistration] = {}
        for tool in tools:
            self.register(tool)

    def register(self, tool: ReadOnlyTool | ToolRegistration) -> None:
        registration = tool if isinstance(tool, ToolRegistration) else ToolRegistration(tool)
        if not registration.name or registration.name in self._tools:
            raise ValueError("tool names must be non-empty and unique")
        self._tools[registration.name] = registration

    def has(self, name: str) -> bool:
        return name in self._tools

    def registration(self, name: str) -> ToolRegistration | None:
        return self._tools.get(name)

    def definitions(self, names: Iterable[str] | None = None) -> tuple[dict[str, object], ...]:
        selected = tuple(sorted(self._tools)) if names is None else tuple(sorted(set(names)))
        definitions = []
        for name in selected:
            registration = self._tools.get(name)
            if registration is None:
                raise ToolAuthorizationError(name)
            definitions.append(registration.tool.definition)
        return tuple(definitions)

    async def execute(self, call: ToolCall, invocation: AgentInvocation) -> ToolResult:
        if call.name not in invocation.execution_policy.allowed_tools:
            raise ToolAuthorizationError(call.name)
        registration = self._tools.get(call.name)
        if registration is None:
            raise ToolAuthorizationError(call.name)
        context = ToolContext(
            invocation_id=invocation.identity.invocation_id,
            agent_id=invocation.identity.agent_id,
            call_id=call.call_id,
            tool_name=call.name,
            scope=invocation.scope,
            context_input=invocation.context_input,
            read_policy=ToolReadPolicy(
                observed_at_utc=invocation.context.prepared_at_utc,
                conversation_id=invocation.context.scope.conversation_id,
                upper_sequence=invocation.context.scope.observation_upper_sequence,
                source_versions=invocation.context.source_versions,
            ),
        )
        result = await registration.tool.invoke(call.arguments, context)
        if result.call_id != call.call_id or result.name != call.name:
            raise ValueError("Tool result identity does not match its call")
        return result
