import json
from collections.abc import Mapping
from string import Template
from zoneinfo import ZoneInfo

from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.agents.contracts.input import InvocationInput
from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.contracts.recovery import FailureCategory
from echo_commons.agents.contracts.refs import OutputContractRef
from echo_commons.agents.harness.context import PromptContext
from echo_commons.agents.harness.prompt import (
    actor_label,
    read_prompt_examples,
    read_prompt_resource,
    render_environment,
    render_prompt_section,
)
from echo_commons.infrastructure.models.protocol import PromptMessage
from echo_commons.modules.reflection.contexts.actors import relationship_evidence
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
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.message_sources import SystemSource


def render_node_task(source_refs: tuple[str, ...]) -> str:
    sources = "\n".join(f"- {ref}" for ref in source_refs) or "- 当前没有可引用来源"
    common = Template(read_prompt_resource("reflection/task.md")).substitute(source_refs=sources)
    return common


def render_material(
    material: ReflectionMaterial, labels: NodeReferences | None = None, *, timezone: str = "UTC"
) -> str:
    if isinstance(material, MessageMaterial):
        message = material.message
        own = ActorRef("character", labels.node.scope.character_id) if labels else None
        sender = (
            actor_label(message.sender, message.sender_name, own)
            if isinstance(message.sender, ActorRef)
            else message.sender_name
        )
        if labels and not isinstance(message.sender, SystemSource):
            number = next(
                (n for n, actor in labels.targets().items() if actor == message.sender), None
            )
            if number is not None:
                sender += f"（人物{number}）"
        content = f"发送者：{sender}\n原话：{message.text}"
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
                content = (
                    f"发送者：{sender}\n回复材料{reply[0]}（{reply[1]}）\n原话：{message.text}"
                )
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
        if material.kind == "game_event" and material.description is not None:
            content = material.description
        if material.kind == "thought":
            content = "本人当时的私有认识与感受：\n" + content
        if labels and material.kind == "formal_fact":
            content = json.dumps(labels.display_record(json.loads(content)), ensure_ascii=False)
        kind = {
            "thought": "conversation_thought",
            "game_event": "game_event",
            "segment_summary": "memory_segment_summary",
            "conversation_digest": "conversation_digest",
            "author_chunk": "author_material",
            "formal_fact": "formal_fact",
        }[material.kind]
        if material.kind == "formal_fact":
            kind = {"memory_fact": "事实记录", "memory_cognition": "角色认识"}.get(
                material.fact_kind, "formal_fact"
            )
        occurred = material.occurred_at_utc if material.kind in ("thought", "game_event") else None
    timestamp = (
        f" (消息记录时间：{occurred.astimezone(ZoneInfo(timezone)):%Y-%m-%d %H:%M:%S} {timezone})"
        if occurred is not None
        else ""
    )
    reference = labels.source_label(material.evidence_ref) if labels else material.evidence_ref
    reference = f"材料{reference}" if labels else reference
    return render_prompt_section(
        "source_material", f"[{reference}] {kind}{timestamp}\n{content.strip()}"
    )


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
    messages = [
        PromptMessage(
            role="system",
            content=render_prompt_section(
                "reflection_instructions", read_prompt_resource("reflection/common.md")
            ),
        )
    ]
    instruction = Template(read_prompt_resource(definition.prompt_resource)).substitute(
        core_memory_max_chars=max_content_chars or 600,
        relationship_attitude_max_chars=max_content_chars or 300,
    )
    messages.append(
        PromptMessage(
            role="system", content=render_prompt_section("node_instructions", instruction)
        )
    )
    if snapshot.node_kind in (
        ReflectionNodeKind.SEGMENT_SUMMARY_PLAN,
        ReflectionNodeKind.CONTINUITY_COMPRESS,
    ):
        messages.append(
            PromptMessage(
                role="system",
                content=render_prompt_section(
                    "summary_guidance", read_prompt_resource("reflection/summary.md")
                ),
            )
        )
        if graph.summary_task is not None:
            purpose = {
                "segment": "回想这一段时间新发生的事情。",
                "continuity": "将已有回忆与新增摘要整理成连续回忆。",
                "complete_experience": "这段活动已经关闭。本次整理完整经历，包含结束前的后续交流。",
            }[graph.summary_task.purpose]
            periods = []
            for period in graph.summary_task.activity_ranges:
                through = period.materials_through_utc.astimezone(
                    ZoneInfo(graph.environment.timezone)
                )
                closing = (
                    "活动关闭于"
                    + period.closed_at_utc.astimezone(
                        ZoneInfo(graph.environment.timezone)
                    ).isoformat()
                    if period.closed_at_utc
                    else "活动尚未关闭"
                )
                periods.append(
                    f"参与编号{period.participation_id}，会话{period.conversation_id}："
                    f"本批材料截至{through.isoformat()}；{closing}。"
                )
            messages.append(
                PromptMessage(
                    role="system",
                    content=render_prompt_section("summary_task", "\n".join((purpose, *periods))),
                )
            )
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
            content=render_prompt_section(
                "output_contract",
                "本节点的输出 JSON Schema：\n" + json.dumps(schema, ensure_ascii=False),
            ),
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
            role="system",
            content=render_prompt_section(
                "material_guidance", read_prompt_resource(f"reflection/materials/{scenario}.md")
            ),
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
    if graph.activity_sessions:
        messages.append(
            PromptMessage(
                role="system",
                content=render_prompt_section(
                    "activity_sessions",
                    json.dumps(
                        [
                            {
                                **s.model_dump(mode="json", exclude={"rules"}),
                                "winners": [p.model_dump(mode="json") for p in s.winners],
                            }
                            for s in graph.activity_sessions
                        ],
                        ensure_ascii=False,
                    ),
                ),
            )
        )
    messages.extend(
        PromptMessage(role="system", content=render_prompt_section(name, content))
        for name, content in zip(
            ("current_state", "relationship_state", "continuity_memory"),
            (projection.state, projection.relationships, projection.memory),
            strict=True,
        )
        if content
    )
    if output_contract.version == "v6":
        messages.extend(
            PromptMessage(role="system", content="本段回忆背景：\n" + artifact.payload.summary)
            for artifact in snapshot.artifacts
            if artifact.payload.kind == "segment_summary"
        )
    if labels:
        names = labels.actor_names()
        own = ActorRef("character", graph.scope.character_id)
        messages.append(
            PromptMessage(
                role="system",
                content=render_prompt_section(
                    "participant_identities",
                    "人物表：\n"
                    + "本人："
                    + actor_label(own, graph.self.name, own)
                    + "\n"
                    + "\n".join(
                        f"人物{number}："
                        + actor_label(actor, names.get(actor, actor.kind.value), own)
                        for number, actor in labels.targets().items()
                    ),
                ),
            )
        )
        if snapshot.node_kind is ReflectionNodeKind.SEGMENT_SUMMARY_PLAN:
            own = ActorRef("character", snapshot.scope.character_id)
            rules = []
            for number, actor in labels.targets().items():
                direct, relevant = relationship_evidence(projection.materials, actor, own)
                rules.append(
                    {
                        "target": number,
                        "direct_sources": sorted(labels.source_label(ref) for ref in direct),
                        "allowed_sources": sorted(labels.source_label(ref) for ref in relevant),
                    }
                )
            messages.append(
                PromptMessage(
                    role="system",
                    content="关系安排的依据范围：每个目标的 sources 至少包含一项 direct_sources，"
                    "全部来源只能从该目标的 allowed_sources 选择。第三人的发言只作为理解背景。\n"
                    + json.dumps(rules, ensure_ascii=False),
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
            content=render_prompt_section(
                "community_environment",
                render_environment(graph.environment) + "\n材料的消息记录时间只说明这句话何时说出；"
                "其中提到的旧事、相对日期与约定分别理解。",
            ),
        )
    )
    messages.append(
        PromptMessage(
            role="system",
            content=render_prompt_section(
                "source_materials",
                "本次材料与只读背景（前情不能作为新变化依据）：\n"
                + render_material_groups(graph, projection.materials, labels),
            ),
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
            content=render_prompt_section(
                "source_contract",
                render_node_task(
                    tuple(
                        f"材料{n}"
                        for n in sorted(
                            set(labels.sources) | set(labels.records) | set(labels.candidates)
                        )
                    )
                    if labels
                    else projection.evidence_refs,
                ),
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
            else (item.conversation_id if item.kind in ("thought", "game_event") else "memory")
        )
        groups.setdefault(scene, []).append(item)
    blocks = []
    for identity, items in groups.items():
        scene = next(
            (value for value in graph.conversations if value.conversation_id == identity), None
        )
        header = (
            scene.name
            + {
                "direct": "｜私人交流",
                "game": "｜活动交流",
                "group": "｜群内交流",
            }[scene.kind]
            if scene
            else "自身记忆与背景"
        )
        if all(item.kind in ("message", "thought", "game_event") for item in items):
            items = sorted(
                items,
                key=lambda item: (
                    item.message.occurred_at_utc
                    if item.kind == "message"
                    else item.occurred_at_utc,
                    item.sequence or 0 if item.kind == "game_event" else 0,
                ),
            )
        blocks.append(
            header + "\n" + render_scene_materials(items, labels, graph.environment.timezone)
        )
    return "\n\n".join(blocks)


def render_scene_materials(items, labels, timezone):
    blocks, actions = [], []

    def flush():
        if not actions:
            return
        first = actions[0]
        when = first.occurred_at_utc.astimezone(ZoneInfo(timezone)).isoformat()
        lines = []
        for item in actions:
            ref = labels.source_label(item.evidence_ref) if labels else item.evidence_ref
            lines.append(f"[材料{ref}] {item.description}")
        prefix = "只读前情：\n" if first.context_only else ""
        blocks.append(
            render_prompt_section(
                "action_record", prefix + f"{when}，同一次动作的正式记录：\n" + "\n".join(lines)
            )
        )
        actions.clear()

    for item in items:
        if item.kind == "game_event" and item.description is not None:
            if actions:
                first = actions[0]
                if (item.game_id, item.participation_id, item.version, item.context_only) != (
                    first.game_id,
                    first.participation_id,
                    first.version,
                    first.context_only,
                ):
                    flush()
            actions.append(item)
        else:
            flush()
            blocks.append(
                ("只读前情，不能作为新变化依据：\n" if item.context_only else "")
                + render_material(item, labels, timezone=timezone)
            )
    flush()
    return "\n\n".join(blocks)
