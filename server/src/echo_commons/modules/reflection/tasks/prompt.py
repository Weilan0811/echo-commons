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
    ReflectionNodeDefinition,
    ReflectionNodeKind,
    reflection_graph_definition,
)
from echo_commons.modules.reflection.tasks.projection import NodeReferences, project_node_input
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
        relationship_attitude_max_chars=max_content_chars or 300,
    )
    return common + "\n\n" + instruction


def render_material(material: ReflectionMaterial, labels: NodeReferences | None = None) -> str:
    if isinstance(material, MessageMaterial):
        message = material.message
        sender = (
            message.sender_name
            if labels
            else f"{message.sender_name}（{message_source_id(message.sender)}）"
        )
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
    timestamp = f" ({occurred.isoformat()})" if occurred is not None else ""
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
) -> PromptContext:
    if not isinstance(snapshot, ReflectionNodeInput):
        raise ExecutionError("agent_input_contract_invalid", FailureCategory.CONFIGURATION)
    outputs.schema(output_contract)
    graph = snapshot.graph_snapshot
    definition = reflection_graph_definition(graph.graph_kind).node(snapshot.node_key)
    projection = project_node_input(snapshot)
    labels = (
        NodeReferences.from_input(snapshot)
        if output_contract.version in ("v5", "v3")
        or output_contract.kind == "reflection_fact_review"
        else None
    )
    messages = [PromptMessage(role="system", content=read_prompt_resource("reflection/common.md"))]
    messages.extend(
        PromptMessage(role="system", content=render_prompt_section(name, content))
        for name, content in projection.identity_sections
    )
    messages.extend(
        PromptMessage(role="system", content=labels.display_text(content) if labels else content)
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
            + "\n\n".join(render_material(item, labels) for item in projection.materials),
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
    last = max(
        (item.last_sequence for item in projection.materials if item.kind == "segment_summary"),
        default=None,
    )
    messages.append(
        PromptMessage(
            role="user",
            content=render_node_task(
                definition,
                tuple(
                    f"材料{n}"
                    for n in sorted(
                        set(labels.sources) | set(labels.records) | set(labels.candidates)
                    )
                )
                if labels
                else projection.evidence_refs,
                last,
                max_content_chars,
            ),
        )
    )
    schema = node_action_schema(definition.action_kind, allow_no_op=definition.allow_no_op)
    if labels:
        choices = sorted(set(labels.sources) | set(labels.records) | set(labels.candidates))
        if snapshot.node_kind in (
            ReflectionNodeKind.FACT_EXTRACT,
            ReflectionNodeKind.COGNITION_REFLECT,
        ):
            item = schema["$defs"]["ExtractedMemory"]
            item["properties"]["sources"]["items"]["enum"] = choices
        elif snapshot.node_kind is not ReflectionNodeKind.FACT_REVIEW:
            schema["properties"]["sources"]["items"]["enum"] = choices
    messages.append(
        PromptMessage(
            role="user",
            content="本节点的完整输出 JSON Schema：\n" + json.dumps(schema, ensure_ascii=False),
        )
    )
    return PromptContext(messages=tuple(messages), tool_definitions=tool_definitions)
