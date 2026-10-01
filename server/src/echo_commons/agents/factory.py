"""Build the default local Character Agent from the model registry."""

from __future__ import annotations

from echo_server.agents.character import CharacterAgent
from echo_server.agents.contracts import RunnableAgent
from echo_server.agents.harness import EchoNativeBackend, ReadOnlyTool, ToolRegistration
from echo_server.agents.stubs import StubCharacterAgent
from echo_server.config import Settings
from echo_server.observability.debug_capture import AgentDebugCapture
from echo_server.services.model_gateway import (
    ModelCredentialError,
    ModelRegistry,
    OpenAICompatibleGateway,
    load_model_registry,
)


def build_default_character_agent(
    settings: Settings,
    *,
    tools: tuple[ReadOnlyTool | ToolRegistration, ...] = (),
    model_registry: ModelRegistry | None = None,  # ------仅测试用模块-----
) -> RunnableAgent:
    """Build the configured Character Agent without changing failure routing."""

    character_id = settings.default_character_id
    agent_id = f"{character_id}.character"
    registry = model_registry or load_model_registry(
        settings.model_registry_path, settings.model_secrets_path
    )
    if not registry.should_use_real_agent():
        return CharacterAgent(
            StubCharacterAgent(),
            character_id=character_id,
            agent_id=agent_id,
        )
    entry = registry.resolve()
    if registry.credential_for(entry) is None:
        raise ModelCredentialError("active model provider is not configured")
    debug_capture = AgentDebugCapture.from_settings(settings)
    backend = EchoNativeBackend(
        OpenAICompatibleGateway(registry, debug_capture=debug_capture),
        agent_id=agent_id,
        agent_kind="character",
        model_profile=registry.active_profile,
        routing=registry.task_routing,
        tools=tools,
        debug_capture=debug_capture,
    )
    return CharacterAgent(
        backend,
        character_id=character_id,
        agent_id=agent_id,
        available_tools=tuple(tool.name for tool in tools),
    )
