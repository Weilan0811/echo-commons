import sqlite3

from echo_commons.agents.character.agent import CharacterAgent
from echo_commons.agents.contracts.capabilities import (
    AgentCapabilities,
    AgentDescriptor,
    AgentPurposeCapabilities,
)
from echo_commons.agents.contracts.invocation import InvocationPurpose
from echo_commons.agents.contracts.output import CHARACTER_MESSAGE_CONTRACT
from echo_commons.agents.contracts.run import RunnableAgent
from echo_commons.agents.factory import build_character_agent
from echo_commons.infrastructure.models.routing import TaskRouting
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.templates.catalog import BlueprintCatalog


class AgentRegistry:
    def __init__(
        self,
        instances: InstanceReader,
        catalog: BlueprintCatalog,
        backend: RunnableAgent,
        capabilities: CapabilityResolver,
        routing: TaskRouting,
    ) -> None:
        self.instances, self.catalog, self.backend = instances, catalog, backend
        self.capabilities, self.routing = capabilities, routing

    def resolve(
        self, connection: sqlite3.Connection, community_id: str, character_id: str
    ) -> CharacterAgent:
        instance = self.instances.get(connection, community_id, character_id)
        blueprint = self.catalog.blueprints[instance.blueprint_id]
        if blueprint.content_version != instance.blueprint_version:
            raise ValueError("Instance blueprint version is unavailable")
        tools = self.capabilities.tools(blueprint, self.capabilities.implemented_tools)
        route = self.routing.route_for("conversation_reply")
        descriptor = AgentDescriptor(
            agent_id=f"character:{community_id}:{character_id}",
            agent_kind="character",
            harness_version="harness-v1",
            model_profile=route.resolved_profile,
            capabilities=AgentCapabilities(
                purpose_capabilities=(
                    AgentPurposeCapabilities(
                        purpose=InvocationPurpose.CONVERSATION_REPLY,
                        allowed_output_contracts=(CHARACTER_MESSAGE_CONTRACT,),
                        allowed_tools=tools,
                    ),
                )
            ),
        )
        return build_character_agent(
            self.backend, character_id=character_id, descriptor=descriptor, routing=self.routing
        )
