from __future__ import annotations

import json
from typing import Protocol

from pydantic import BaseModel, ConfigDict

from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.infrastructure.models.protocol import PromptMessage, ToolCall


class PromptContext(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    tool_definitions: tuple[dict[str, object], ...] = ()
    messages: tuple[PromptMessage, ...] = ()

    def with_observation(
        self,
        *,
        tool_name: str,
        call_id: str,
        ok: bool,
        output: dict[str, object],
        error_code: str | None = None,
        progressed: bool | None = None,
        new_item_count: int = 0,
        no_progress_streak: int | None = None,
    ) -> PromptContext:
        observation = {
            "tool": tool_name,
            "call_id": call_id,
            "ok": ok,
            "output": output,
        }
        if error_code is not None:
            observation["error_code"] = error_code
        if progressed is not None:
            observation["progressed"] = progressed
            observation["new_item_count"] = new_item_count
            observation["no_progress_streak"] = no_progress_streak
        content = json.dumps(observation, ensure_ascii=False, separators=(",", ":"))
        return self.model_copy(
            update={
                "messages": (
                    *self.messages,
                    PromptMessage(
                        role="tool",
                        content=content,
                        metadata={"tool_call_id": call_id},
                    ),
                ),
            }
        )

    def with_tool_definitions(
        self,
        tool_definitions: tuple[dict[str, object], ...],
    ) -> PromptContext:
        return self.model_copy(update={"tool_definitions": tool_definitions})

    def with_user_instruction(self, content: str) -> PromptContext:
        return self.model_copy(
            update={
                "messages": (
                    *self.messages,
                    PromptMessage(role="user", content=content),
                ),
            }
        )

    def with_assistant_output(self, output: dict[str, object]) -> PromptContext:
        return self.model_copy(
            update={
                "messages": (
                    *self.messages,
                    PromptMessage(
                        role="assistant",
                        content=json.dumps(output, ensure_ascii=False, separators=(",", ":")),
                    ),
                ),
            }
        )

    def with_repair_instruction(self, error_code: str, hint: str) -> PromptContext:
        return self.with_user_instruction(f"上一轮输出未通过校验。错误码：{error_code}。{hint}")

    def with_tool_calls(self, tool_calls: tuple[ToolCall, ...]) -> PromptContext:
        """Append the provider-native assistant tool-call envelope."""

        if not tool_calls:
            return self
        serialized = [
            {
                "id": call.call_id,
                "type": "function",
                "function": {
                    "name": call.name,
                    "arguments": json.dumps(
                        call.arguments,
                        ensure_ascii=False,
                        separators=(",", ":"),
                    ),
                },
            }
            for call in tool_calls
        ]
        return self.model_copy(
            update={
                "messages": (
                    *self.messages,
                    PromptMessage(
                        role="assistant",
                        content="",
                        metadata={"tool_calls": serialized},
                    ),
                )
            }
        )


class InputReadiness(Protocol):
    async def check(self, invocation: AgentInvocation) -> None: ...


class InputProjector(Protocol):
    def __call__(
        self,
        snapshot: InvocationInput,
        *,
        output_contract: OutputContractRef,
        outputs: OutputRegistry,
        tool_definitions: tuple[dict[str, object], ...] = (),
    ) -> PromptContext: ...
