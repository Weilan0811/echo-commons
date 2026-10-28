from echo_commons.agents.contracts.execution import ExecutionLimits
from echo_commons.agents.contracts.invocation import InvocationPurpose
from echo_commons.agents.contracts.output import (
    CHARACTER_EXPRESSION_CONTRACT,
    CHARACTER_EXPRESSION_TYPE,
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.agents.harness.runner import HarnessBackend
from echo_commons.agents.harness.tools import ToolRegistration, ToolRegistry
from echo_commons.infrastructure.models.openai_compatible import OpenAICompatibleGateway
from echo_commons.infrastructure.models.registry import load_model_registry
from echo_commons.infrastructure.observability.debug_capture import AgentDebugCapture
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.services.capabilities import CapabilityResolver
from echo_commons.modules.characters.services.registry import AgentPurposeBinding, AgentRegistry
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.conversations.tasks.execution import (
    ConversationExecution,
)
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.modules.memory.tools.search import MemorySearchTool, memory_progress
from echo_commons.shared.actors import ActorRef
from support.application import settings_for
from support.recovery import conversation_recovery
from support.social import build_planning_system, send


def prepare_system(tmp_path, *, lookup_text=None, mentions=()):
    system = build_planning_system(tmp_path)
    for character, text in (("first", "私有词榆树702"), ("second", "私有词松树903")):
        private_conversation = "private-" + character
        system.conversations.create(
            "community",
            "direct",
            (ActorRef("player", "alice"), ActorRef("character", character)),
            conversation_id=private_conversation,
        )
        system.intake.send("community", private_conversation, PlayerMessage("alice", text, text))
    send(
        system,
        lookup_text or "你还记得我在私聊里告诉你的私有词是什么吗？请查找记忆再告诉我，别猜。",
        mentions=mentions,
    )
    system.planner.plan()
    with system.database.read() as connection:
        system.task_ids = tuple(
            row[0]
            for row in connection.execute(
                "SELECT task_id FROM conversation_tasks WHERE conversation_id = 'conversation' "
                "ORDER BY character_id"
            )
        )
    return attach_execution(system, tmp_path)


def attach_execution(system, tmp_path):
    outputs = OutputRegistry()
    outputs.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)
    outputs.register(CHARACTER_EXPRESSION_CONTRACT, CHARACTER_EXPRESSION_TYPE)
    settings = settings_for(tmp_path, workers=False)
    models = load_model_registry(settings.model_registry_path, settings.model_secrets_path)
    capture = AgentDebugCapture(tmp_path / "capture")
    gateway = OpenAICompatibleGateway(models, debug_capture=capture)
    tool = MemorySearchTool(system.database, system.retrieval, max_results=5)
    tools = (ToolRegistration(tool, memory_progress),)
    backend = HarnessBackend(
        gateway, outputs=outputs, projector=project_snapshot, tools=tools, debug_capture=capture
    )
    registry = AgentRegistry(
        InstanceRepository(),
        system.catalog,
        {
            InvocationPurpose.CONVERSATION_REPLY: AgentPurposeBinding(
                backend, (CHARACTER_MESSAGE_CONTRACT, CHARACTER_EXPRESSION_CONTRACT)
            )
        },
        CapabilityResolver(frozenset({"memory_search"})),
        models.task_routing,
    )
    system.executor = ConversationExecution(
        system.database, system.tasks, registry, ExecutionLimits(), conversation_recovery(system)
    )
    system.gateway, system.outputs, system.tool_registry = gateway, outputs, ToolRegistry(tools)
    system.capture = capture
    return system
