from pydantic import BaseModel, ConfigDict

from echo_commons.agents.contracts.invocation import InvocationPurpose
from echo_commons.agents.contracts.refs import OutputContractRef


class AgentPurposeCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    purpose: InvocationPurpose
    allowed_output_contracts: tuple[OutputContractRef, ...]
    allowed_tools: tuple[str, ...] = ()


class AgentCapabilities(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    purpose_capabilities: tuple[AgentPurposeCapabilities, ...]

    def for_purpose(self, purpose: InvocationPurpose) -> AgentPurposeCapabilities:
        for item in self.purpose_capabilities:
            if item.purpose == purpose:
                return item
        raise ValueError(f"Agent does not support purpose: {purpose}")


class AgentDescriptor(BaseModel):
    model_config = ConfigDict(extra="forbid", frozen=True)
    agent_id: str
    agent_kind: str
    harness_version: str
    model_profile: str
    capabilities: AgentCapabilities
