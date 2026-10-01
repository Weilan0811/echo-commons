"""Read-only tool port for the internal Agent Loop."""

from __future__ import annotations

from collections.abc import Iterable, Mapping
from dataclasses import dataclass
from typing import Protocol
from uuid import UUID

from pydantic import BaseModel, ConfigDict, Field

from echo_server.agents.contracts import AgentInvocation, ContextSnapshotV2
from echo_server.agents.harness.progress import ToolProgressExtractor
from echo_server.services.model_gateway.protocol import ToolCall


class ToolExecutionError(RuntimeError):
    code = "tool_execution_error"


class ToolAuthorizationError(ToolExecutionError):
    code = "tool_not_allowed"


class ToolContext(BaseModel):
    """Only immutable invocation data is exposed to a local tool."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    invocation_id: UUID
    agent_id: str
    call_id: str
    tool_name: str
    snapshot: ContextSnapshotV2


class ToolResult(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    call_id: str
    name: str
    ok: bool
    output: dict[str, object] = Field(default_factory=dict)
    error_code: str | None = None


class ReadOnlyTool(Protocol):
    name: str

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
        """Return OpenAI-compatible function definitions for enabled tools.

        Tool implementations may provide a richer ``definition`` mapping.  The
        permissive fallback keeps the existing read-only test tools compatible
        while still making the action boundary explicit to a model.
        """

        selected = tuple(sorted(self._tools)) if names is None else tuple(sorted(set(names)))
        definitions: list[dict[str, object]] = []
        for name in selected:
            registration = self._tools.get(name)
            if registration is None:
                continue
            tool = registration.tool
            raw_definition = getattr(tool, "definition", None)
            if callable(raw_definition):
                raw_definition = raw_definition()
            if isinstance(raw_definition, Mapping):
                definition = dict(raw_definition)
                if "function" in definition:
                    definitions.append(definition)
                    continue
                definitions.append(
                    {
                        "type": "function",
                        "function": definition,
                    }
                )
                continue
            description = getattr(tool, "description", "")
            parameters = getattr(tool, "parameters", None)
            if not isinstance(parameters, Mapping):
                parameters = {
                    "type": "object",
                    "additionalProperties": True,
                }
            definitions.append(
                {
                    "type": "function",
                    "function": {
                        "name": name,
                        "description": description or f"Read the {name} capability.",
                        "parameters": dict(parameters),
                    },
                }
            )
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
            snapshot=invocation.context,
        )
        result = await registration.tool.invoke(call.arguments, context)
        if not isinstance(result, ToolResult):
            result = ToolResult.model_validate(result)
        if result.call_id != call.call_id or result.name != call.name:
            result = result.model_copy(update={"call_id": call.call_id, "name": call.name})
        return result
