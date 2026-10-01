from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from echo_commons.agents.contracts import AgentInvocation, AgentRunResult
from echo_commons.agents.harness.loop import AgentLoop, utc_now
from echo_commons.agents.harness.policy import HarnessPolicy
from echo_commons.agents.harness.tools import ReadOnlyTool, ToolRegistration, ToolRegistry
from echo_commons.infrastructure.observability.debug_capture import AgentDebugCapture, run_with_debug_capture
from echo_commons.infrastructure.models import ModelRoute, TaskRouting
from echo_commons.infrastructure.models.protocol import ModelGateway


class EchoNativeBackend:
    """Echo-owned backend composed from Gateway, policy and tools."""

    agent_kind = "character"

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        agent_id: str = "harness-agent",
        agent_kind: str = "character",
        model_profile: str = "light",
        tools: tuple[ReadOnlyTool | ToolRegistration, ...] = (),
        policy: HarnessPolicy | None = None,
        clock: Callable[[], datetime] = utc_now,
        routing: TaskRouting | None = None,
        debug_capture: AgentDebugCapture | None = None,
    ) -> None:
        self.agent_id = agent_id
        self.agent_kind = agent_kind
        self.model_profile = model_profile
        self.routing = routing or TaskRouting(default_profile=model_profile)
        self.policy = policy or HarnessPolicy()
        self.harness_version = self.policy.harness_version
        self.debug_capture = debug_capture
        self._loop = AgentLoop(
            gateway,
            tools=ToolRegistry(tools),
            policy=self.policy,
            clock=clock,
        )

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        return await run_with_debug_capture(
            self.debug_capture,
            invocation,
            backend=self.__class__.__name__,
            operation=lambda: self._loop.run(invocation),
        )

    def route_for(self, task_kind: str) -> ModelRoute:
        """Resolve the logical model profile for a Runtime task."""

        return self.routing.route_for(task_kind)


__all__ = ["EchoNativeBackend"]
