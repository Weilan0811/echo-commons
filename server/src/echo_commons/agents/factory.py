from echo_commons.agents.character.agent import CharacterAgent
from echo_commons.agents.contracts.capabilities import AgentDescriptor
from echo_commons.agents.contracts.run import RunnableAgent
from echo_commons.infrastructure.models.routing import TaskRouting


def build_character_agent(
    backend: RunnableAgent, *, character_id: str, descriptor: AgentDescriptor, routing: TaskRouting
) -> CharacterAgent:
    return CharacterAgent(
        backend, character_id=character_id, descriptor=descriptor, routing=routing
    )
