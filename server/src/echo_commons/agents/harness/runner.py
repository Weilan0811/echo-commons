from __future__ import annotations

from collections.abc import Callable
from datetime import datetime

from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.run import AgentRunResult
from echo_commons.agents.harness.context import InputProjector, InputReadiness
from echo_commons.agents.harness.loop import AgentLoop, utc_now
from echo_commons.agents.harness.policy import HarnessPolicy
from echo_commons.agents.harness.tools import ReadOnlyTool, ToolRegistration, ToolRegistry
from echo_commons.infrastructure.models.protocol import ModelGateway
from echo_commons.infrastructure.observability.debug_capture import (
    AgentDebugCapture,
    run_with_debug_capture,
)


class HarnessBackend:
    """模型、只读工具与执行预算组成的通用后端。"""

    def __init__(
        self,
        gateway: ModelGateway,
        *,
        outputs: OutputRegistry,
        projector: InputProjector,
        input_readiness: InputReadiness | None = None,
        tools: tuple[ReadOnlyTool | ToolRegistration, ...] = (),
        policy: HarnessPolicy | None = None,
        clock: Callable[[], datetime] = utc_now,
        debug_capture: AgentDebugCapture | None = None,
    ) -> None:
        self.policy = policy or HarnessPolicy()
        self.harness_version = self.policy.harness_version
        self.debug_capture = debug_capture
        self.input_readiness = input_readiness
        self._loop = AgentLoop(
            gateway,
            outputs=outputs,
            projector=projector,
            input_readiness=input_readiness,
            tools=ToolRegistry(tools),
            policy=self.policy,
            clock=clock,
        )

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        if self.input_readiness is not None:
            await self.input_readiness.check(invocation)
        return await run_with_debug_capture(
            self.debug_capture,
            invocation,
            backend=self.__class__.__name__,
            operation=lambda: self._loop.run(invocation),
        )
