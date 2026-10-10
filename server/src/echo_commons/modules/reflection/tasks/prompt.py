import json
from string import Template

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.recovery import FailureCategory
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.prompt import read_prompt_resource, render_prompt_section
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.modules.reflection.contracts.context import (
    MessageMaterial,
    ReflectionMaterial,
    ReflectionNodeInput,
)
from echo_commons.modules.reflection.domain.graph import (
    ReflectionNodeDefinition,
    ReflectionNodeKind,
    reflection_graph_definition,
)
from echo_commons.modules.reflection.tasks.projection import project_node_input
from echo_commons.shared.message_sources import SystemSource, message_source_id


def render_node_task(
    definition: ReflectionNodeDefinition,
    source_refs: tuple[str, ...],
    last_sequence: int | None = None,
    max_content_chars: int | None = None,
) -> str:
    sources = "\n".join(f"- {ref}" for ref in source_refs) or "- 当前没有可引用来源"
    common = Template(read_prompt_resource("reflection/task.md")).substitute(source_refs=sources)
    instruction = Template(read_prompt_resource(definition.prompt_resource)).substitute(
        last_sequence=last_sequence or 0,
        core_memory_max_chars=max_content_chars or 600,
    )
    return common + "\n\n" + instruction


def render_material(material: ReflectionMaterial) -> str:
    if isinstance(material, MessageMaterial):
        message = material.message
        content = (
            f"发送者：{message.sender_name}（{message.sender.kind.value}:"
            f"{message_source_id(message.sender)}）\n{message.text}"
        )
        kind = (
            "system"
            if isinstance(message.sender, SystemSource)
            else "conversation_character"
            if message.sender.kind == "character"
            else "conversation_player"
        )
        occurred = message.occurred_at_utc
    else:
        content = material.content
        kind = {
            "thought": "conversation_thought",
            "segment_summary": "memory_segment_summary",
            "conversation_digest": "conversation_digest",
            "author_chunk": "author_material",
            "formal_fact": "formal_fact",
        }[material.kind]
        occurred = material.occurred_at_utc if material.kind == "thought" else None
    timestamp = f" ({occurred.isoformat()})" if occurred is not None else ""
    return f"[{material.evidence_ref}] {kind}{timestamp}\n{content.strip()}"


def project_node(
    snapshot: InvocationInput,
    *,
    output_contract: OutputContractRef,
    outputs: OutputRegistry,
    tool_definitions: tuple[dict[str, object], ...] = (),
    max_content_chars: int | None = None,
) -> PromptContext:
    if not isinstance(snapshot, ReflectionNodeInput):
        raise ExecutionError("agent_input_contract_invalid", FailureCategory.CONFIGURATION)
    outputs.schema(output_contract)
    graph = snapshot.graph_snapshot
    definition = reflection_graph_definition(graph.graph_kind).node(snapshot.node_key)
    projection = project_node_input(snapshot)
    messages = [PromptMessage(role="system", content=read_prompt_resource("reflection/common.md"))]
    messages.extend(
        PromptMessage(role="system", content=render_prompt_section(name, content))
        for name, content in projection.identity_sections
    )
    messages.extend(
        PromptMessage(role="system", content=content)
        for content in (projection.state, projection.relationships, projection.memory)
        if content
    )
    if snapshot.node_kind in {
        ReflectionNodeKind.RELATIONSHIP_REFLECT,
        ReflectionNodeKind.RELATIONSHIP_ATTITUDE_VIEW,
    }:
        messages.append(
            PromptMessage(
                role="system", content=read_prompt_resource("common/relationship-dimensions.md")
            )
        )
    if snapshot.node_kind is ReflectionNodeKind.RELATIONSHIP_REFLECT:
        targets = sorted(source_actors(graph), key=lambda item: (item.kind.value, item.actor_id))
        messages.append(
            PromptMessage(
                role="system",
                content="本次关系分析的 target 只能从以下身份对象中选择：\n"
                + json.dumps(
                    [dict(kind=item.kind.value, actor_id=item.actor_id) for item in targets],
                    ensure_ascii=False,
                )
                + "\n当前角色实例标识："
                + graph.scope.character_id,
            )
        )
    scenario = {
        "author_material_batch": "author",
        "memory_change_set": "facts",
        "memory_segment": "dialogue",
        "memory_summary_batch": "dialogue",
    }[graph.source_kind]
    messages.append(
        PromptMessage(
            role="system",
            content=read_prompt_resource(f"reflection/materials/{scenario}.md")
            + "\n\n本次可以引用的来源材料：\n"
            + "\n\n".join(render_material(item) for item in projection.materials),
        )
    )
    if projection.reading_scope is not None:
        messages.append(
            PromptMessage(
                role="system",
                content=render_prompt_section(
                    "reading_scope",
                    json.dumps(projection.reading_scope.prompt_data(), ensure_ascii=False),
                ),
            )
        )
    if snapshot.artifacts:
        messages.append(
            PromptMessage(
                role="system",
                content="前驱节点分析背景：\n"
                + json.dumps(
                    [item.payload.model_dump(mode="json") for item in snapshot.artifacts],
                    ensure_ascii=False,
                ),
            )
        )
    last = max(
        (item.last_sequence for item in projection.materials if item.kind == "segment_summary"),
        default=None,
    )
    messages.append(
        PromptMessage(
            role="user",
            content=render_node_task(definition, projection.evidence_refs, last, max_content_chars),
        )
    )
    return PromptContext(messages=tuple(messages), tool_definitions=tool_definitions)
