import json

from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.prompt import (
    render_node_responsibility,
    render_node_task,
    render_output_contract,
    render_prompt_section,
    render_reflection_source_introduction,
)
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.modules.reflection.contexts.actors import source_actors
from echo_commons.modules.reflection.contracts.context import MessageMaterial, ReflectionNodeInput
from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind
from echo_commons.modules.reflection.tasks.projection import project_node_input
from echo_commons.shared.message_sources import SystemSource, message_source_id


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
    projection = project_node_input(snapshot)
    messages = [
        PromptMessage(role="system", content=render_output_contract(output_contract.schema_id)),
        PromptMessage(role="system", content=render_node_responsibility(snapshot.node_kind)),
    ]
    messages.extend(
        PromptMessage(role="system", content=render_prompt_section(name, content))
        for name, content in projection.identity_sections
    )
    messages.extend(
        PromptMessage(role="system", content=content)
        for content in (
            projection.state,
            projection.relationships,
            projection.memory,
        )
        if content
    )
    if snapshot.node_kind is ReflectionNodeKind.RELATIONSHIP_REFLECT:
        targets = sorted(
            source_actors(graph), key=lambda target: (target.kind.value, target.actor_id)
        )
        messages.append(
            PromptMessage(
                role="system",
                content="本次关系分析的 target 只能从以下身份对象中选择：\n"
                + json.dumps(
                    [
                        {"kind": target.kind.value, "actor_id": target.actor_id}
                        for target in targets
                    ],
                    ensure_ascii=False,
                )
                + "\n当前角色实例标识："
                + graph.scope.character_id,
            )
        )
    materials = []
    for material in projection.materials:
        if isinstance(material, MessageMaterial):
            message = material.message
            content = (
                f"发送者：{message.sender_name}（{message.sender.kind.value}:"
                f"{message_source_id(message.sender)}）\n{message.text}"
            )
            source_kind = (
                "system"
                if isinstance(message.sender, SystemSource)
                else "conversation_character"
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
        occurred = (
            message.occurred_at_utc
            if isinstance(material, MessageMaterial)
            else material.occurred_at_utc
            if material.kind == "thought"
            else None
        )
        timestamp = f" ({occurred.isoformat()})" if occurred is not None else ""
        materials.append(f"[{material.evidence_ref}] {source_kind}{timestamp}\n{content.strip()}")
    messages.append(
        PromptMessage(
            role="system",
            content=render_reflection_source_introduction()
            + "\n\n本次可以引用的来源材料：\n"
            + "\n\n".join(materials),
        )
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
                projection.evidence_refs,
                last,
            ),
        )
    )
    return PromptContext(messages=tuple(messages), tool_definitions=tool_definitions)
