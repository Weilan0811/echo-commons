from __future__ import annotations

from dataclasses import dataclass

from echo_commons.agents.contracts import AgentInvocation


@dataclass(frozen=True, slots=True)
class HarnessPolicy:
    harness_version: str = "harness-v1"
    max_model_steps: int = 8
    max_model_requests: int = 8
    max_tool_calls: int = 8
    max_repairs_per_error: int = 1
    max_no_progress_streak: int = 2

    def __post_init__(self) -> None:
        if self.max_model_steps < 1:
            raise ValueError("max_model_steps must be positive")
        if self.max_model_requests < 1:
            raise ValueError("max_model_requests must be positive")
        if self.max_tool_calls < 0:
            raise ValueError("max_tool_calls must not be negative")
        if self.max_repairs_per_error < 0:
            raise ValueError("max_repairs_per_error must not be negative")
        if self.max_no_progress_streak < 1:
            raise ValueError("max_no_progress_streak must be positive")

    def model_step_limit(self, invocation: AgentInvocation) -> int:
        return min(self.max_model_steps, invocation.execution_policy.max_model_steps)

    def model_request_limit(self, invocation: AgentInvocation) -> int:
        requested = invocation.execution_policy.max_model_requests or self.max_model_requests
        return min(self.max_model_requests, requested)

    def tool_call_limit(self, invocation: AgentInvocation) -> int:
        return min(self.max_tool_calls, invocation.execution_policy.max_tool_calls)
