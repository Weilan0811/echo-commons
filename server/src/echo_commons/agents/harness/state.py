from __future__ import annotations

from dataclasses import dataclass, field

from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.run import (
    AgentOutput,
    AgentStep,
    RepairObservation,
    UsageSummary,
)
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.progress import ToolProgressState


@dataclass(slots=True)
class HarnessControlState:
    disabled_tools: set[str] = field(default_factory=set)
    tool_progress: dict[str, ToolProgressState] = field(default_factory=dict)
    repair_counts: dict[str, int] = field(default_factory=dict)

    def progress_for(self, tool_name: str) -> ToolProgressState:
        return self.tool_progress.setdefault(tool_name, ToolProgressState())

    def disable_tool(self, tool_name: str) -> None:
        self.disabled_tools.add(tool_name)

    def enabled_tools(self, allowed_tools: tuple[str, ...]) -> tuple[str, ...]:
        return tuple(name for name in allowed_tools if name not in self.disabled_tools)

    def record_repair(self, error_code: str) -> int:
        count = self.repair_counts.get(error_code, 0) + 1
        self.repair_counts[error_code] = count
        return count

    @property
    def repair_count(self) -> int:
        return sum(self.repair_counts.values())


@dataclass(slots=True)
class AgentRunState:
    invocation: AgentInvocation
    prompt_context: PromptContext
    steps: list[AgentStep] = field(default_factory=list)
    output: AgentOutput | None = None
    usage_summary: UsageSummary = field(default_factory=UsageSummary)
    control: HarnessControlState = field(default_factory=HarnessControlState)
    provider_attempt_count: int | None = 0
    repair_observations: list[RepairObservation] = field(default_factory=list)

    @property
    def step_count(self) -> int:
        return len(self.steps)

    @property
    def model_request_count(self) -> int:
        return self.usage_summary.model_request_count

    @property
    def tool_call_count(self) -> int:
        return self.usage_summary.tool_call_count

    def add_usage(self, usage: UsageSummary) -> None:
        self.usage_summary = self.usage_summary.add(usage)

    def add_step(self, step: AgentStep) -> None:
        self.steps.append(step)
