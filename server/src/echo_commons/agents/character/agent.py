from echo_commons.agents.contracts.capabilities import AgentDescriptor
from echo_commons.agents.contracts.invocation import AgentInvocation
from echo_commons.agents.contracts.run import AgentRunResult, RunnableAgent
from echo_commons.infrastructure.models.routing import ModelRoute, TaskRouting


class CharacterAgent:
    def __init__(
        self,
        backend: RunnableAgent,
        *,
        character_id: str,
        descriptor: AgentDescriptor,
        routing: TaskRouting,
    ) -> None:
        if not character_id.strip() or descriptor.agent_kind != "character":
            raise ValueError("character identity and descriptor are required")
        self.backend = backend
        self.character_id = character_id
        self.descriptor = descriptor
        self.routing = routing

    def route_for(self, task_kind: str) -> ModelRoute:
        return self.routing.route_for(task_kind)

    async def run(self, invocation: AgentInvocation) -> AgentRunResult:
        if (
            invocation.identity.agent_id != self.descriptor.agent_id
            or invocation.identity.agent_kind != self.descriptor.agent_kind
        ):
            raise ValueError("invocation does not belong to this agent")
        if invocation.scope.character_id != self.character_id:
            raise ValueError("invocation character does not match agent")
        capability = self.descriptor.capabilities.for_purpose(invocation.identity.purpose)
        if invocation.output_contract not in capability.allowed_output_contracts:
            raise ValueError("output exceeds agent capabilities")
        if not set(invocation.execution_policy.allowed_tools).issubset(capability.allowed_tools):
            raise ValueError("tools exceed agent capabilities")
        return await self.backend.run(invocation)
