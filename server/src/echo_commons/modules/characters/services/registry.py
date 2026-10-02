import sqlite3
from dataclasses import dataclass
from types import MappingProxyType

from echo_commons.agents.character.agent import CharacterAgent
from echo_commons.agents.contracts.capabilities import (
    AgentCapabilities,
    AgentDescriptor,
    AgentPurposeCapabilities,
)
from echo_commons.agents.contracts.invocation import InvocationPurpose
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.contracts.run import RunnableAgent
from echo_commons.agents.factory import build_character_agent
from echo_commons.infrastructure.models.routing import TaskRouting
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.templates.catalog import BlueprintCatalog


@dataclass(frozen=True, slots=True)
class AgentPurposeBinding:
    backend: RunnableAgent
    output_contracts: tuple[OutputContractRef, ...]


class AgentRegistry:
    def __init__(
        self,
        instances: InstanceReader,
        catalog: BlueprintCatalog,
        bindings: dict[InvocationPurpose, AgentPurposeBinding],
        capabilities: CapabilityResolver,
        routing: TaskRouting,
    ) -> None:
        self.instances, self.catalog = instances, catalog
        self.bindings = MappingProxyType(dict(bindings))
        self.capabilities, self.routing = capabilities, routing

    def resolve(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        *,
        purpose: InvocationPurpose,
    ) -> CharacterAgent:
        instance = self.instances.get(connection, community_id, character_id)
        blueprint = self.catalog.blueprints[instance.blueprint_id]
        if blueprint.content_version != instance.blueprint_version:
            raise ValueError("Instance blueprint version is unavailable")
        tools = self.capabilities.tools(blueprint, self.capabilities.implemented_tools)
        binding = self.bindings[purpose]
        route = self.routing.route_for(purpose.value)
        descriptor = AgentDescriptor(
            agent_id=f"character:{community_id}:{character_id}",
            agent_kind="character",
            harness_version="harness-v1",
            model_profile=route.resolved_profile,
            capabilities=AgentCapabilities(
                purpose_capabilities=(
                    AgentPurposeCapabilities(
                        purpose=purpose,
                        allowed_output_contracts=binding.output_contracts,
                        allowed_tools=tools,
                    ),
                )
            ),
        )
        return build_character_agent(
            binding.backend, character_id=character_id, descriptor=descriptor, routing=self.routing
        )
