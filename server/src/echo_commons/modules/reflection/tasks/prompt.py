import json

from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.prompt import (
    render_identity,
    render_memory,
    render_node_responsibility,
    render_node_task,
    render_output_contract,
    render_prompt_section,
    render_relationships,
    render_state,
)
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.modules.reflection.contracts.context import MessageMaterial, ReflectionNodeInput


def project_node(
    snapshot: InvocationInput,
    *,
    output_contract: OutputContractRef,
    outputs: OutputRegistry,
    tool_definitions: tuple[dict[str, object], ...] = (),
) -> PromptContext:
    if not isinstance(snapshot, ReflectionNodeInput):
        raise ValueError("Reflection projector requires a reflection node input")
    outputs.schema(output_contract)
    graph = snapshot.graph_snapshot
    messages = [
        PromptMessage(role="system", content=render_output_contract(output_contract.schema_id)),
        PromptMessage(role="system", content=render_node_responsibility(snapshot.node_kind)),
    ]
    messages.extend(
        PromptMessage(role="system", content=render_prompt_section(name, content))
        for name, content in render_identity(graph.self, include_voice=False)
    )
    messages.extend(
        PromptMessage(role="system", content=content)
        for content in (
            render_state(graph.self),
            render_relationships(graph.self),
            render_memory(graph.memory),
        )
        if content
    )
    materials = []
    for material in graph.materials:
        if isinstance(material, MessageMaterial):
            message = material.message
            content = (
                f"发送者：{message.sender_name}（{message.sender.kind.value}:"
                f"{message.sender.actor_id}）\n{message.text}"
            )
            source_kind = (
                "conversation_character"
                if message.sender.kind == "character"
                else "conversation_player"
            )
        else:
            content = material.content
            source_kind = {
                "thought": "conversation_thought",
                "segment_summary": "memory_segment_summary",
                "conversation_digest": "conversation_digest",
            }[material.kind]
        materials.append(f"[{material.evidence_ref}] {source_kind}\n{content.strip()}")
    messages.append(
        PromptMessage(role="system", content="可引用来源材料：\n" + "\n\n".join(materials))
    )
    if snapshot.artifacts:
        messages.append(
            PromptMessage(
                role="system",
                content="前驱节点分析背景：\n"
                + json.dumps(
                    [artifact.payload.model_dump(mode="json") for artifact in snapshot.artifacts],
                    ensure_ascii=False,
                ),
            )
        )
    last = max(
        (
            material.last_sequence
            for material in graph.materials
            if material.kind == "segment_summary"
        ),
        default=None,
    )
    messages.append(
        PromptMessage(
            role="user",
            content=render_node_task(
                snapshot.node_kind,
                tuple(material.evidence_ref for material in graph.materials),
                last,
            ),
        )
    )
    return PromptContext(messages=tuple(messages), tool_definitions=tool_definitions)
