import json
from collections.abc import Mapping
from string import Template

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.recovery import FailureCategory
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.prompt import (
    read_prompt_examples,
    read_prompt_resource,
    render_prompt_section,
)
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.modules.reflection.contracts.candidates import (
    MemoryFactExtractAction,
    node_action_schema,
)
from echo_commons.modules.reflection.contracts.context import (
    MessageMaterial,
    ReflectionMaterial,
    ReflectionNodeInput,
)
from echo_commons.modules.reflection.domain.graph import (
    ReflectionNodeKind,
    reflection_graph_definition,
)
from echo_commons.modules.reflection.tasks.projection import NodeReferences, project_node_input
from echo_commons.shared.message_sources import SystemSource, message_source_id


def render_node_task(source_refs: tuple[str, ...]) -> str:
    sources = "\n".join(f"- {ref}" for ref in source_refs) or "- 当前没有可引用来源"
    common = Template(read_prompt_resource("reflection/task.md")).substitute(source_refs=sources)
    return common


def render_material(material: ReflectionMaterial, labels: NodeReferences | None = None) -> str:
    if isinstance(material, MessageMaterial):
        message = material.message
        sender = (
            message.sender_name
            if labels
            else f"{message.sender_name}（{message_source_id(message.sender)}）"
        )
        if labels and not isinstance(message.sender, SystemSource):
            number = next(
                (n for n, actor in labels.targets().items() if actor == message.sender), None
            )
            if number is not None:
                sender += f"（人物{number}）"
        content = f"发送者：{sender}\n{message.text}"
        if labels and message.reply_to_message_id:
            reply = next(
                (
                    (number, original.message.sender_name)
                    for number, original in labels.originals.items()
                    if original.kind == "message"
                    and original.source_id == message.reply_to_message_id
                ),
                None,
            )
            if reply is not None:
                content = f"发送者：{sender}\n回复材料{reply[0]}（{reply[1]}）\n{message.text}"
        if message.visibility in ("私人交流", "仅指定受众可见"):
            content += "\n范围：私人内容，仅原指定受众可知"
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
        if labels and material.kind == "formal_fact":
            content = json.dumps(labels.display_record(json.loads(content)), ensure_ascii=False)
        kind = {
            "thought": "conversation_thought",
            "segment_summary": "memory_segment_summary",
            "conversation_digest": "conversation_digest",
            "author_chunk": "author_material",
            "formal_fact": "formal_fact",
        }[material.kind]
        if material.kind == "formal_fact":
            kind = {"memory_fact": "事实记录", "memory_cognition": "角色认识"}.get(
                material.fact_kind, "formal_fact"
            )
        occurred = material.occurred_at_utc if material.kind == "thought" else None
    timestamp = f" ({occurred:%m-%d %H:%M:%S})" if occurred is not None else ""
    reference = labels.source_label(material.evidence_ref) if labels else material.evidence_ref
    reference = f"材料{reference}" if labels else reference
    return f"[{reference}] {kind}{timestamp}\n{content.strip()}"


def project_node(
    snapshot: InvocationInput,
    *,
    output_contract: OutputContractRef,
    outputs: OutputRegistry,
    tool_definitions: tuple[dict[str, object], ...] = (),
    max_content_chars: int | None = None,
    examples: Mapping[str, str] | None = None,
) -> PromptContext:
    if not isinstance(snapshot, ReflectionNodeInput):
        raise ExecutionError("agent_input_contract_invalid", FailureCategory.CONFIGURATION)
    outputs.schema(output_contract)
    graph = snapshot.graph_snapshot
    definition = reflection_graph_definition(graph.graph_kind).node(snapshot.node_key)
    projection = project_node_input(snapshot)
    labels = (
        NodeReferences.from_input(snapshot)
        if output_contract.version in ("v5", "v3", "v6")
        or output_contract.kind == "reflection_fact_review"
        else None
    )
    messages = [PromptMessage(role="system", content=read_prompt_resource("reflection/common.md"))]
    instruction = Template(read_prompt_resource(definition.prompt_resource)).substitute(
        core_memory_max_chars=max_content_chars or 600,
        relationship_attitude_max_chars=max_content_chars or 300,
    )
    messages.append(PromptMessage(role="system", content=instruction))
    schema = node_action_schema(definition.action_kind, allow_no_op=definition.allow_no_op)
    if snapshot.node_kind in {
        ReflectionNodeKind.CORE_MEMORY_VIEW,
        ReflectionNodeKind.RELATIONSHIP_ATTITUDE_VIEW,
    }:
        schema["properties"]["content"]["maxLength"] = max_content_chars or (
            600 if snapshot.node_kind is ReflectionNodeKind.CORE_MEMORY_VIEW else 300
        )
    messages.append(
        PromptMessage(
            role="system",
            content="本节点的输出 JSON Schema：\n" + json.dumps(schema, ensure_ascii=False),
        )
    )
    if snapshot.node_kind in {
        ReflectionNodeKind.COGNITION_REFLECT,
        ReflectionNodeKind.CORE_MEMORY_VIEW,
    }:
        example_text = (
            examples[snapshot.node_key]
            if examples is not None and snapshot.node_key in examples
            else read_prompt_examples(snapshot.node_key)
        )
        if example_text:
            messages.append(PromptMessage(role="system", content=example_text))
    scenario = {
        "author_material_batch": "author",
        "memory_change_set": "facts",
        "memory_segment": "dialogue",
        "memory_summary_batch": "dialogue",
    }[graph.source_kind]
    messages.append(
        PromptMessage(
            role="system", content=read_prompt_resource(f"reflection/materials/{scenario}.md")
        )
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
    messages.extend(
        PromptMessage(role="system", content=render_prompt_section(name, content))
        for name, content in projection.identity_sections
    )
    messages.extend(
        PromptMessage(role="system", content=labels.display_text(content) if labels else content)
        for content in (projection.state, projection.relationships, projection.memory)
        if content
    )
    if output_contract.version == "v6":
        messages.extend(
            PromptMessage(role="system", content="本段回忆背景：\n" + artifact.payload.summary)
            for artifact in snapshot.artifacts
            if artifact.payload.kind == "segment_summary"
        )
        names = {
            (relation.target.kind.value, relation.target.actor_id): relation.target_name
            for relation in graph.self.relationships
        }
        names.update(
            (
                (item.message.sender.kind.value, message_source_id(item.message.sender)),
                item.message.sender_name,
            )
            for item in graph.materials
            if item.kind == "message"
        )
        messages.append(
            PromptMessage(
                role="system",
                content="人物表：\n"
                + "\n".join(
                    f"人物{number}："
                    f"{names.get((actor.kind.value, actor.actor_id), actor.kind.value)}"
                    for number, actor in labels.targets().items()
                ),
            )
        )
        if snapshot.node_kind is ReflectionNodeKind.RELATIONSHIP_REFLECT:
            plan = next(
                (
                    artifact.payload.follow_up
                    for artifact in snapshot.artifacts
                    if artifact.payload.kind == "segment_summary"
                ),
                None,
            )
            target_numbers = {actor: number for number, actor in labels.targets().items()}
            messages.append(
                PromptMessage(
                    role="system",
                    content="各目标允许的新材料：\n"
                    + "\n".join(
                        f"人物{target_numbers[item.target]}："
                        + "、".join(f"材料{labels.source_label(ref)}" for ref in item.evidence_refs)
                        for item in plan.relationship_targets
                    )
                    if plan
                    else "本次没有关系目标。",
                )
            )
    messages.append(
        PromptMessage(
            role="system",
            content="本次材料与只读背景（前情不能作为新变化依据）：\n"
            + render_material_groups(graph, projection.materials, labels),
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
    if labels and labels.predecessor_text():
        messages.append(
            PromptMessage(role="system", content="前驱事实材料：\n" + labels.predecessor_text())
        )
    if snapshot.node_kind is ReflectionNodeKind.FACT_REVIEW:
        extracted = next(
            item.payload
            for item in snapshot.artifacts
            if isinstance(item.payload, MemoryFactExtractAction)
        )
        messages.append(
            PromptMessage(
                role="system",
                content="本批候选事实：\n"
                + "\n\n".join(
                    f"[候选{number}] {item.fact.content}\n依据："
                    + ", ".join(f"材料{labels.source_label(ref)}" for ref in item.evidence_refs)
                    for number, item in enumerate(extracted.facts, 1)
                ),
            )
        )
    elif snapshot.artifacts and not labels:
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
    messages.append(
        PromptMessage(
            role="user",
            content=render_node_task(
                tuple(
                    f"材料{n}"
                    for n in sorted(
                        set(labels.sources) | set(labels.records) | set(labels.candidates)
                    )
                )
                if labels
                else projection.evidence_refs,
            ),
        )
    )
    if labels and output_contract.version == "v6":
        messages.append(
            PromptMessage(
                role="user",
                content="本次新依据 sources 只可使用："
                + json.dumps([n for n, item in labels.originals.items() if not item.context_only])
                + "\n本次 target 只可使用："
                + json.dumps(list(labels.targets())),
            )
        )
    return PromptContext(messages=tuple(messages), tool_definitions=tool_definitions)


def render_material_groups(graph, materials, labels):
    groups = {}
    for item in materials:
        scene = (
            item.message.conversation_id
            if item.kind == "message"
            else (item.conversation_id if item.kind == "thought" else "memory")
        )
        groups.setdefault(scene, []).append(item)
    blocks = []
    for identity, items in groups.items():
        scene = next(
            (value for value in graph.conversations if value.conversation_id == identity), None
        )
        header = (
            scene.name + ("｜私人交流" if scene.kind == "direct" else "｜群内交流")
            if scene
            else "自身记忆与背景"
        )
        blocks.append(
            header
            + "\n"
            + "\n\n".join(
                ("只读前情，不能作为新变化依据：\n" if item.context_only else "")
                + render_material(item, labels)
                for item in items
            )
        )
    return "\n\n".join(blocks)
