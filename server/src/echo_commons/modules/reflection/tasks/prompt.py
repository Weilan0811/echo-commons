import json

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.recovery import FailureCategory
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
        raise ExecutionError("agent_input_contract_invalid", FailureCategory.CONFIGURATION)
    outputs.schema(output_contract)
    graph = snapshot.graph_snapshot
    projection = project_node_input(snapshot)
    view_instructions = {
        ReflectionNodeKind.CORE_MEMORY_VIEW: (
            "整理角色此刻最重要、值得常驻保留的记忆认识。只引用正式长期页，保留作者背景与亲身经历的区别。"
            "返回 kind=view_refresh、view_kind=core_memory、content，"
            "并在 supporting_memory_ids 中填写实际引用的页标识。"
            "不适合保留核心认识时返回有明确理由的 no_op。"
        ),
        ReflectionNodeKind.STATE_SUMMARY_VIEW: (
            "依据当前有效的状态记录概括角色的身体、心情和活动。保持简短，不添加经历或改动状态事实。"
            "返回 kind=view_refresh、view_kind=state_summary、content；没有可靠认识时返回 no_op。"
        ),
        ReflectionNodeKind.RELATIONSHIP_ATTITUDE_VIEW: (
            "依据这一个对象的正式关系状态描述角色对他的态度。数值仅用于理解关系，不能建议修改数值。"
            "返回 kind=view_refresh、view_kind=relationship_attitude、content，"
            "并填写 target 的 kind 和 actor_id。"
            "态度应与正式关系及证据一致；证据不足时返回 no_op。"
        ),
    }
    messages = [
        PromptMessage(role="system", content=render_output_contract(output_contract.schema_id)),
        PromptMessage(role="system", content=render_node_responsibility(snapshot.node_kind)),
    ]
    messages.extend(
        PromptMessage(role="system", content=render_prompt_section(name, content))
        for name, content in projection.identity_sections
    )
    if snapshot.node_kind in view_instructions:
        messages.append(PromptMessage(role="system", content=view_instructions[snapshot.node_kind]))
        if snapshot.node_kind is ReflectionNodeKind.CORE_MEMORY_VIEW:
            messages.append(
                PromptMessage(
                    role="system",
                    content=(
                        "supporting_memory_ids 必须是下面列出的原始 memory_id，"
                        "不加 formal_fact: 或 memory_entry: 前缀：\n"
                        + json.dumps(
                            [item.source_id for item in projection.materials], ensure_ascii=False
                        )
                    ),
                )
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
        messages.append(
            PromptMessage(
                role="system",
                content=(
                    "每个 dimensions 项的 evidence_kind 标记本次互动证据：interaction 普通互动、"
                    "support 真实帮助与支持、conflict 明确冲突、commitment 实际承诺。"
                    "同一个对象的全部维度使用同一分类，按来源中确实发生的行为选择；"
                    "不能把角色猜测或希望当作对方已经做出的支持与承诺。"
                ),
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
                "author_chunk": "author_material",
                "formal_fact": "formal_fact",
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
    if graph.source_kind == "author_material_batch":
        messages.append(
            PromptMessage(
                role="system",
                content=(
                    "这些材料是作者设定的过去故事与日常采访。保留作者设定、习惯、过去经历的区别，"
                    "不要把习惯写成今日事实，也不要把故事人物当作当前社群成员。"
                    "采访中的观点与猜想应保留其主观含义。使用作者片段标识追溯来源。"
                ),
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
