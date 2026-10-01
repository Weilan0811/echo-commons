"""Agent capability declarations used by Runtime policy and tests."""

from __future__ import annotations

from pydantic import BaseModel, ConfigDict, Field

from echo_server.agents.contracts.invocation import InvocationPurpose
from echo_server.agents.contracts.refs import OutputContractRef


class AgentPurposeCapabilities(BaseModel):
    """Per-purpose output Contract and tool permissions for one Agent descriptor."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    purpose: InvocationPurpose
    allowed_output_contracts: tuple[OutputContractRef, ...] = ()
    allowed_tools: tuple[str, ...] = ()

    def allows_output_contract(self, contract: OutputContractRef) -> bool:
        if self.allowed_output_contracts:
            return contract.schema_id in {item.schema_id for item in self.allowed_output_contracts}
        if self.purpose is InvocationPurpose.CONVERSATION_REPLY:
            return contract.schema_id == "character_message.v2"
        if self.purpose is InvocationPurpose.REFLECTION:
            return contract.schema_id == "reflection_node.v1"
        return False


class AgentCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)

    allowed_output_contracts: tuple[OutputContractRef, ...] = ()
    allowed_tools: tuple[str, ...] = ()
    max_model_steps: int = Field(default=1, ge=1)
    max_tool_calls: int = Field(default=0, ge=0)
    purpose_capabilities: tuple[AgentPurposeCapabilities, ...] = ()

    @property
    def supported_invocation_purposes(self) -> tuple[InvocationPurpose, ...]:
        if self.purpose_capabilities:
            return tuple(item.purpose for item in self.purpose_capabilities)
        return (InvocationPurpose.CONVERSATION_REPLY,)

    def for_purpose(self, purpose: InvocationPurpose) -> AgentPurposeCapabilities | None:
        for item in self.purpose_capabilities:
            if item.purpose is purpose:
                return item
        if purpose is InvocationPurpose.CONVERSATION_REPLY and not self.purpose_capabilities:
            return AgentPurposeCapabilities(
                purpose=purpose,
                allowed_output_contracts=self.allowed_output_contracts,
                allowed_tools=self.allowed_tools,
            )
        return None


class AgentDescriptor(BaseModel):
    """Catalog metadata; Runtime remains the authority that applies it."""

    model_config = ConfigDict(extra="forbid", frozen=True)

    agent_id: str
    agent_kind: str
    harness_version: str
    model_profile: str = "light"
    capabilities: AgentCapabilities = Field(default_factory=AgentCapabilities)


__all__ = ["AgentCapabilities", "AgentDescriptor", "AgentPurposeCapabilities"]
