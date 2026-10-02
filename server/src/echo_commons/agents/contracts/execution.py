from dataclasses import dataclass

from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.run import RunnableAgent


@dataclass(frozen=True, slots=True)
class ExecutionLimits:
    model_steps: int = 8
    model_requests: int = 8
    tool_calls: int = 8
    max_output_tokens: int | None = None
    temperature: float | None = None
    top_p: float | None = None
    output_instructions: str = ""


@dataclass(frozen=True, slots=True)
class PreparedExecution:
    agent: RunnableAgent
    invocation: AgentInvocation
