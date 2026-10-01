from __future__ import annotations

from collections.abc import Iterable

from echo_commons.agents.contracts.context import (
    ActiveThread,
    CharacterStateSnapshot,
    ContextSnapshotV2,
    IdentityContext,
    MemoryItem,
    RelationshipStateSnapshot,
    SessionDigest,
    SituationView,
)
from echo_commons.agents.contracts.proposals import (
    CHARACTER_MESSAGE_OUTPUT_SCHEMA,
    REFLECTION_NODE_OUTPUT_SCHEMA,
)
from echo_commons.agents.contracts.reflection_context import ReflectionContext
from echo_commons.agents.contracts.reflection_graph import NodeInput

CHARACTER_MESSAGE_OUTPUT_SCHEMA_TEMPLATE = """{
  "thought": "string",
  "utterance": "string"
}"""

REFLECTION_NODE_OUTPUT_SCHEMA_TEMPLATE = """{
  "kind": "segment_summary | relationship_reflection | state_reflection |
continuity_digest | long_term_memory_page | graph_extraction | diary | view_refresh | no_op",
  "evidence_refs": ["message:<id>", "thought:<id>"]
}"""

_AVAILABILITY_SENTENCES = {
    "available": "你现在有空，可以自然地回应对方。",
    "busy": "你手头还有自己的事情，但能分一点心思回应对方。",
    "offline": "你现在不在线，回应会显得断断续续。",
    "story_absent": "你暂时不在眼前这段生活里，没法像平时那样回应。",
    "technical_error": "你现在的状态不太稳定，没法像平时那样回应。",
}

_RELATIONSHIP_TYPE_SENTENCES = {
    "stranger": "你和对方目前还是陌生人。",
    "acquaintance": "你和对方已经是熟人。",
    "friend": "你和对方已经是朋友。",
}

_NODE_RESPONSIBILITIES = {
    "segment_summary_plan": (
        "你负责把当前来源段整理成角色以后能回想起来的一段经历。"
        "先看清这段时间发生了什么、角色当时有什么真实感受，再决定是否值得继续做关系或状态分析。"
    ),
    "relationship_reflect": (
        "你负责从当前来源判断关系的三个维度有没有出现可记录的变化。"
        "分别看 affection（好感）、trust（信任）和 attachment（依恋），只列出材料能够支持的变化。"
    ),
    "state_reflect": (
        "你负责从当前来源判断角色自身有没有出现可记录的状态变化。"
        "只选择 physical（身体）、mood（心境）或 activity（活动）中的一个类别，并写下当前状态。"
    ),
    "page_compose": (
        "你负责从当前批次整理角色以后能够独立回想和再次使用的长期记忆。"
        "每条独立记忆分别写成一个 page，不把多个无关事实拼成一条。"
    ),
    "graph_extract": (
        "你负责从当前批次提取可以复用的实体和实体关系，供长期记忆图使用。"
        "实体和关系在同一个 action 中一起返回，只保留来源能够支持的内容。"
    ),
    "continuity_compress": (
        "你负责把上一条连续性摘要和当前按时间排列的段摘要，整理成一条可以继续使用的会话连续性摘要。"
        "保留重要事件、持续中的约定、未解决的事情和关系变化。"
    ),
}

_MEMORY_ORGANIZE_SOURCE_GUIDANCE = (
    (
        "memory_segment_summary 提供已经审核过的整体背景；conversation_character 表示角色说过的"
        "话；conversation_thought 表示角色当时的内心注意、感受或判断；conversation_player 只能"
        "证明玩家这样说过，不能单独证明角色已经确认或记住了这件事。"
    ),
    (
        "常驻记忆只用于理解背景和发现重复，不能填写到 evidence_refs；常驻记忆不完整也不能证明"
        "当前内容一定是新的。当前状态、关系状态和角色设定同样不能替代本次来源材料。"
    ),
)


def render_output_contract(output_schema: str) -> str:
    """生成本次调用的输出协议。

    稳定的身份、记忆和能力规则来自 Identity 资源。
    """

    lines = ["请只返回一个 JSON 对象。"]
    if output_schema == CHARACTER_MESSAGE_OUTPUT_SCHEMA:
        lines.extend(
            [
                (
                    "对象只能包含 thought 和 utterance 两个字段；utterance 必须是非空字符串，"
                    "thought 可以为空。"
                ),
                (
                    "thought 只记录角色此刻真实冒出来的一点内心反应：正在注意什么、有什么感受，"
                    "或突然想到什么。它可以只有几个字或一句短话；没有值得记录的念头就写空字符串。"
                    "thought 不承担回复计划、对话分析、模型推理或规则说明；这个字段不会展示给玩家。"
                ),
                (
                    "utterance 只写角色此刻会发给对方的原话，让它承担角色真正的回应。"
                    "回复按这一刻的聊天节奏来写：可以很短，也可以在自然停顿处分成几段；"
                    "换行只表示真实停顿或本来会分开的说话，不为了显得热闹而插入，"
                    "也不因为换行额外补话。换行符在 JSON 字符串中写作 \\n。"
                ),
                "不要输出 Markdown、解释、日志或 JSON 之外的文字，也不要谈论自己正在执行什么要求。",
                "字段名和层级请与下面的格式示意保持一致。",
                CHARACTER_MESSAGE_OUTPUT_SCHEMA_TEMPLATE,
            ]
        )
    elif output_schema == REFLECTION_NODE_OUTPUT_SCHEMA:
        lines.extend(
            [
                (
                    "你现在做的是角色自己的回看。以角色本人的身份阅读这些材料，"
                    "把已经发生、确实感受到或确实记住的内容整理成当前节点允许的 action；"
                    "不确定的地方就保留不确定。"
                ),
                (
                    "角色资料说明你是谁；当前窗口的来源材料说明这次实际发生了什么。"
                    "常驻记忆、当前状态、关系状态和前置 Artifact 用来理解背景；"
                    "本次关系或状态的新变化，只根据当前节点允许引用的来源判断。"
                ),
                (
                    "凡是输出摘要、记忆、日记、状态或关系视图等正文，都从角色第一人称写成"
                    "以后能够自然回想的内容；结构化字段只使用规定的枚举、数值和来源字符串。"
                ),
                (
                    "evidence_refs 只填写输入中显示、且属于当前节点允许范围的来源字符串，"
                    "例如 message:<id> 或 thought:<id>。前置 Artifact 可以帮助理解，"
                    "但不能替代本次来源引用。"
                ),
                (
                    "没有可以可靠归纳的内容时返回 kind=no_op 并填写 reason。"
                    "来源字符串、版本、时间、ID 和其他 Runtime 字段都由输入或 Runtime 提供。"
                ),
                (
                    "最后的节点说明会给出当前节点的字段结构。只填写当前节点允许的字段，"
                    "保持一个 JSON action；Runtime 会检查字段名称、类型和取值。"
                ),
                "字段名和层级请与下面的格式示意保持一致。",
                REFLECTION_NODE_OUTPUT_SCHEMA_TEMPLATE,
            ]
        )
    else:
        lines.append("字段结构遵循本次对话约定，并保持为一个 JSON 对象。")
    if output_schema != CHARACTER_MESSAGE_OUTPUT_SCHEMA:
        lines.append("不要输出 Markdown、解释、日志、额外文字，也不要谈论自己正在执行什么要求。")
    return "\n".join(lines)


def render_conversation_guidance() -> str:
    """生成一次角色消息调用的对话表达规则。

    稳定的身份和事实边界来自 ``agent-contract.md``；这里只说明如何把这些前提
    组织成一条自然的回复。
    """

    return "\n\n".join(
        [
            (
                "从角色此刻的生活、记忆、感受和正在发生的事出发回应。先看对方这一句真正说了什么，"
                "再按你自己的反应说；没有需要展开时，短短回一句也足够。话题可以停在自然的位置。"
            ),
            (
                "聊天节奏由当前内容决定。回复的长短、停顿和分段跟着你这次真正想说的量走；"
                "长消息不必全部解释，短消息也不自动变成长话题。对方的短回复有时只是短回复，"
                "先回应它本身；只有你确实从上下文感觉到别的意思时，才去猜测或追问。"
            ),
            (
                "thought 是角色随手留下的私有内心，不是每轮必须完成的思考步骤。"
                "有念头就写最先冒出来的那一点，"
                "几个字、一小句都可以；没有就留空。它可以不完整、保留、犹豫，或和说出口的话不同。"
                "让它像角色当下会有的念头，不要把内容整理成分析、解释或回复方案。"
            ),
            (
                "说话只留下角色此刻会发出去的内容，让自己的反应承担对话。空泛的共情、客服式追问、重复对方的话、"
                "把日常包装成金句的比喻，都不能替代角色自己的反应。像“我懂”“我理解你的感受”"
                "“你有什么想分享的吗”“要不要我给你推荐”“需要我帮你吗”“怎么突然问这个”这类现成话术，"
                "除非角色此刻确实这样想、也确实会这样说，否则不要使用。话题可以停在任何地方，"
                "不需要每次都解释完整、总结完整或留下问题。"
            ),
            (
                "你说话像在手机上和一个人聊天。手机聊天可以只是一点即时反应，也可以带一两句展开。"
                "说到这里已经够了就停；有真想知道的事再问，不需要每次都给对方留下一个问题。"
            ),
            (
                "角色设定只是你生活的底色，不需要每轮拿出来证明自己。只有当前话题碰到了，"
                "或者你此刻真的想到了，才自然带出自己的兴趣、经历和习惯；"
                "不要反复提同一个爱好或性格标签，也不要把个人简介背给对方听。"
            ),
            (
                "每次从当前这一刻开始说，沿用你们已经形成的相处方式，但不要照搬上一轮的开头、句式和问法。"
            ),
        ]
    )


def render_agent_contract(identity: IdentityContext) -> str:
    """Render the common identity and memory rules for every character."""

    return "\n\n".join(
        [
            "无论当前输出的是 utterance、thought 还是 reflection，都以角色本人的身份理解和表达，"
            "始终遵循角色的身份、记忆、能力与表达规则；这些规则适用于全部输出字段。",
            _clean(identity.contract_content),
        ]
    )


def render_character_profile(identity: IdentityContext) -> str:
    """Render the character-specific identity and life history."""

    return _clean(identity.profile_content)


def render_character_relational_dynamics(identity: IdentityContext) -> str:
    """Render the character-specific relationship tendencies."""

    return _clean(identity.relational_dynamics_content)


def render_character_voice(identity: IdentityContext) -> str:
    """Render the character-specific surface language style."""

    return _clean(identity.voice_content)


def render_identity_sections(
    identity: IdentityContext, *, include_voice: bool = True
) -> tuple[tuple[str, str], ...]:
    """Return common and character resources as separately named sections."""

    sections = [
        ("agent_contract", render_agent_contract(identity)),
        ("character_profile", render_character_profile(identity)),
        ("character_relational_dynamics", render_character_relational_dynamics(identity)),
    ]
    if include_voice:
        sections.append(("character_voice", render_character_voice(identity)))
    return tuple((name, content) for name, content in sections if content)


def render_prompt_section(name: str, content: str) -> str:
    """Wrap one model-facing context block with an explicit source boundary."""

    cleaned = _clean(content)
    if not cleaned:
        return ""
    return f"<{name}>\n{cleaned}\n</{name}>"


def render_resident_memory(items: Iterable[MemoryItem]) -> str:
    """Render the small set of memories that is always close at hand."""

    return _render_memory(
        items,
        heading="你一直记得的一些事情：",
    )


def render_recalled_memory(items: Iterable[MemoryItem]) -> str:
    """Render memories deliberately brought back for this turn."""

    return _render_memory(
        items,
        heading="此刻从更远处浮现出来的一些记忆：",
    )


def render_session_digest(digest: SessionDigest) -> str:
    """Render the conversation summary without exposing its storage metadata."""

    content = _clean(digest.content)
    return f"你对前面这段相处还留着这样的印象：\n{content}" if content else ""


def render_active_threads(threads: Iterable[ActiveThread]) -> str:
    """Render open conversational threads as things still present in mind."""

    lines: list[str] = []
    for thread in threads:
        summary = _clean(thread.summary)
        if not summary:
            continue
        if thread.status == "waiting":
            lines.append(f"- 这件事还在等一个回应：{summary}")
        elif thread.status == "resolved":
            lines.append(f"- 这件事已经暂时告一段落：{summary}")
        else:
            lines.append(f"- {summary}")
    if not lines:
        return ""
    return "你心里还挂着这些事情：\n" + "\n".join(lines)


def render_character_state(state: CharacterStateSnapshot) -> str:
    """Render volatile self-state as ordinary inner-life prose."""

    sentences: list[str] = []
    availability = _AVAILABILITY_SENTENCES.get(state.availability_status)
    if availability:
        sentences.append(availability)
    if _clean(state.physical_condition):
        sentences.append(f"身体状况是{state.physical_condition.strip()}。")
    if _clean(state.mood):
        sentences.append(f"心情是{state.mood.strip()}。")
    if _clean(state.current_activity):
        sentences.append(f"手头正在做的是{state.current_activity.strip()}。")
    if not sentences:
        return ""
    return "你此刻的状态：\n" + " ".join(sentences)


def render_relationship_state(state: RelationshipStateSnapshot) -> str:
    """Render relationship type and attitude without numeric dimensions."""

    sentences: list[str] = []
    relationship_type = _RELATIONSHIP_TYPE_SENTENCES.get(state.relationship_type)
    if relationship_type:
        sentences.append(relationship_type)
    if _clean(state.attitude_summary):
        sentences.append(state.attitude_summary.strip())
    if not sentences:
        return ""
    return "你和对方现在的相处：\n" + " ".join(sentences)


def render_situation(situation: SituationView) -> str:
    """Render perceptible situation details, not Runtime design labels."""

    paragraphs: list[str] = []
    if _clean(situation.ambient_summary):
        paragraphs.append(f"周围给你的感觉是：{situation.ambient_summary.strip()}")
    events = [event.strip() for event in situation.observed_events if _clean(event)]
    if events:
        paragraphs.append("你注意到：\n" + "\n".join(f"- {event}" for event in events))
    if _clean(situation.uncertainty_note):
        paragraphs.append(situation.uncertainty_note.strip())
    if not paragraphs:
        return ""
    return "眼前的情境：\n" + "\n".join(paragraphs)


def render_reflection_window(context: ReflectionContext) -> str:
    """Render bounded Reflection sources with the refs the model must cite."""

    window = context.window
    metadata: list[str] = []
    if window.first_message_sequence is not None:
        metadata.append(f"起始消息序号：{window.first_message_sequence}")
    if window.last_message_sequence is not None:
        metadata.append(f"结束消息序号：{window.last_message_sequence}")
    parts = [
        "这是本次反思可以使用的上下文。下面的来源材料记录了当前窗口实际发生的内容；"
        "状态和关系信息只帮助你理解角色当时所处的位置。"
    ]
    if metadata:
        parts.append("消息范围：\n" + "\n".join(metadata))
    state = render_character_state(context.character_state)
    relationship = render_relationship_state(context.relationship_state)
    if state:
        parts.append(state)
    if relationship:
        parts.append(relationship)
    materials: list[str] = []
    for material in context.materials:
        occurred = (
            f" ({material.occurred_at_utc.isoformat()})"
            if material.occurred_at_utc is not None
            else ""
        )
        materials.append(
            f"[{material.source_ref}] {material.source_kind}{occurred}\n{material.content.strip()}"
        )
    if materials:
        parts.append("本次可以引用的来源材料：\n" + "\n\n".join(materials))
    return "\n\n".join(parts)


def render_node_input(node_input: NodeInput) -> str:
    """Render the model-facing responsibility and source selector guidance."""

    return "\n\n".join(
        (
            render_node_responsibility(node_input.node_kind),
            render_node_task(node_input),
        )
    )


def render_node_responsibility(node_kind: str) -> str:
    """Render stable instructions for one fixed graph node kind."""

    return _NODE_RESPONSIBILITIES.get(
        node_kind,
        "你负责完成当前固定节点声明的反思动作，只基于提供的来源作出可追溯判断。",
    )


def render_node_task(node_input: NodeInput) -> str:
    """Render the changing, node-specific task at the end of the Prompt."""

    source_refs = tuple(item.ref for item in node_input.evidence_refs if item.kind == "source")
    source_lines = "\n".join(f"- {ref}" for ref in source_refs) or "- 当前没有可引用来源"
    common = [
        "本次只返回当前节点的一个 action JSON。",
        "evidence_refs 只填写下面列出的完整来源字符串，原样保留字符串，不添加版本。",
        f"本节点可引用的来源：\n{source_lines}",
        (
            "省略 evidence_refs 时，Runtime 会使用本节点允许范围内的默认来源；"
            "没有有效来源时返回 no_op。"
        ),
        (
            "来源版本、记录时间、状态有效期以及所有 ID 由 Runtime 补齐；"
            "节点专门要求的消息范围字段按后文填写。"
        ),
    ]
    if node_input.node_kind == "segment_summary_plan":
        common.extend(
            [
                "返回 kind=segment_summary 时：填写 summary 和 follow_up。",
                (
                    "summary 是角色留给自己的一小段回忆。写这段时间真正发生的事情，"
                    "以及角色当时确实有过的感受、注意或判断；保留具体细节和没有说完的地方。"
                ),
                (
                    "summary 覆盖本次消息与 thought 能支持的内容，并以第一人称“我”撰写。"
                    "提到另一方时使用“对方”或来源中自然的称呼；让摘要停在经历本身，"
                    "不替这段经历下关系结论。"
                ),
                (
                    "把消息和 thought 一起阅读：thought 帮助你找回角色当时的注意、感受和判断，"
                    "消息决定实际发生的内容。回复计划、猜想和规则说明不写成已经发生的事情。"
                ),
                (
                    "写法可以接近：‘我那天忙到忘了吃饭，跟对方说起这件事。对方催我先去弄点吃的，"
                    "语气有点凶，但我知道他是在关心我。’"
                ),
                (
                    "follow_up 包含 relationship_reflect 和 state_reflect 两个布尔值。"
                    "true 表示值得交给对应节点继续查看，不表示事实已经改变。"
                ),
                "如果来源不足以形成可靠摘要，返回 kind=no_op 和简短 reason。",
            ]
        )
    elif node_input.node_kind == "relationship_reflect":
        common.extend(
            [
                ("kind=relationship_reflection 时，顶层只写 kind、evidence_refs 和 dimensions。"),
                (
                    "这一步记录关系判断本身。把理由放在 evidence_refs 里，"
                    "dimensions 只保留规定的结构。"
                ),
                ("dimensions 是 JSON 数组；每一项包含 dimension、direction、level。"),
                "dimension 使用 affection、trust、attachment，每个维度最多出现一次。",
                (
                    "direction 使用 positive、negative 或 neutral；"
                    "positive 和 negative 的 level 为 1 到 3，"
                    "neutral 的 level 为 0。"
                ),
                (
                    "affection 看当下相处带来的喜欢、亲近或愉快。一次自然、没有冲突的交流，"
                    "通常可以记录 affection 的 positive level 1；只有来源显示不愉快或疏远时，"
                    "才考虑 neutral 或 negative。"
                ),
                (
                    "trust 看角色是否因为对方的可靠、诚实或尊重边界而更放心交流，"
                    "包括愿意让对方知道真实感受。材料出现这些信号时再记录 trust。"
                ),
                (
                    "attachment 看更深的信赖、对对方本人的直接依赖或持续吸引，"
                    "以及想一直保有这段关系、想继续和对方在一起的明确感受。"
                    "普通聊天、一次关心、顺畅接话、习惯聊天或想起对方，本身不足以支持 attachment。"
                ),
                (
                    "负向变化也需要来源中的具体表现，例如失望、受伤、欺骗、越过边界或主动疏远。"
                    "没有对应信号时保持 neutral 或返回 no_op，不把沉默、礼貌和自己的猜想当成变化。"
                ),
                (
                    "level 表示本次来源显示的变化幅度，不是关系总分。一次清楚的信号通常使用 1；"
                    "2 或 3 需要当前窗口中更强或相互印证的信号。"
                ),
                "格式示例（<id> 只是占位符，输出时必须替换成上面列出的完整来源字符串）：\n"
                "{\n"
                '  "kind": "relationship_reflection",\n'
                '  "evidence_refs": ["message:<id>"],\n'
                '  "dimensions": [\n'
                "    {\n"
                '      "dimension": "affection",\n'
                '      "direction": "positive",\n'
                '      "level": 1\n'
                "    }\n"
                "  ]\n"
                "}",
                ("如果来源没有关系变化信号，返回 kind=no_op 和简短 reason。"),
                "关系类型、总分、绝对数值、状态期限和数据库 ID 不属于本节点输出。",
            ]
        )
    elif node_input.node_kind == "state_reflect":
        common.extend(
            [
                (
                    "kind=state_reflection 时，选择一个 state_kind"
                    "（physical、mood、activity）并填写 value。"
                ),
                (
                    "value 用角色第一人称写一句或两句具体的当下体验，"
                    "只记录来源里已经出现的当前状态。"
                    "可以参考："
                    "‘我今天一直在赶稿，脑子有点发木，饭也差点忘了吃。’"
                ),
                (
                    "value 只写状态本身，不写对话总结或关系结论。"
                    "时间、有效期、版本和数据库 ID 由 Runtime 管理。"
                ),
                "如果来源没有可靠的自身状态信号，返回 kind=no_op 和简短 reason。",
            ]
        )
    elif node_input.node_kind == "continuity_compress":
        last_sequence = node_input.projection.window.last_message_sequence
        sequence_guidance = (
            f"本批次最后一条消息序号是 {last_sequence}；"
            "covers_through_sequence 必须原样填写这个数字。"
            if last_sequence is not None
            else "本批次没有可用的结束消息序号，不能生成连续性摘要。"
        )
        common.extend(
            [
                (
                    "当前来源按时间顺序提供：上一条连续性摘要（如果存在）和本批次已经审核过的段摘要。"
                    "上一条摘要只用于保持长期连续性；当前段摘要用于补充新内容和修正已经变化的内容。"
                ),
                (
                    "kind=continuity_digest 时填写 content、covers_through_sequence "
                    "和 evidence_refs。"
                    "content 用角色第一人称写成一条可以在后续对话中直接使用的累计摘要，"
                    "不要逐条复述段摘要，也不要提到摘要、批次、序号、版本或数据库。"
                ),
                (
                    "保留以后仍然有用的事件、约定、承诺、未解决事项、重要偏好和关系变化。"
                    "删除寒暄、重复细节、短期情绪和对后续没有帮助的内容。"
                ),
                (
                    "只写当前材料能够支持的内容。新段摘要与上一条摘要出现差异时，按照当前材料更新；"
                    "材料没有说明的内容保持原样或省略，不自行补全。"
                ),
                sequence_guidance,
                (
                    "本图已经有冻结的摘要批次，只要当前材料存在，就必须返回 continuity_digest。"
                    "不要返回 no_op。上一条摘要可以很短，当前批次仍然必须推进覆盖范围。"
                ),
                "格式示例（<id> 只是占位符，输出时必须替换成输入中的完整来源字符串）：\n"
                "{\n"
                '  "kind": "continuity_digest",\n'
                '  "content": "我记得……",\n'
                f'  "covers_through_sequence": '
                f"{last_sequence if last_sequence is not None else 0},\n"
                '  "evidence_refs": ["summary:<id>"]\n'
                "}",
            ]
        )
    elif node_input.node_kind == "page_compose":
        common.extend(_MEMORY_ORGANIZE_SOURCE_GUIDANCE)
        common.extend(
            [
                (
                    "kind=long_term_memory_page 时，返回 pages 数组；每个 pages 项都是一条"
                    "可以独立检索和回想的长期记忆。"
                ),
                (
                    "当前来源中有多个互相独立的约定、承诺、事件或事实时，分别生成多个 pages 项。"
                    "同一件事被重复提及时合并为一个 pages 项；同一件事的几个细节只有在以后应该"
                    "一起回想时才合并。"
                ),
                (
                    "长期记忆必须有以后仍然有用的具体内容。普通寒暄、一次性安排、没有得到角色支持的"
                    "猜测和只有一瞬间的情绪反应不要写入。常驻记忆只用于理解背景和发现重复，"
                    "不能填写到 evidence_refs。"
                ),
                (
                    "每个 pages 项包含 memory_kind、content、subject_kind、subject_id、"
                    "confidence 和"
                    "salience。memory_kind 使用 fact、event、preference、promise、thread 或 other。"
                ),
                (
                    "content 用角色第一人称写成一条具体记忆，只围绕一个主题。confidence 表示来源对"
                    "这条记忆的支持程度；salience 表示它以后对保持相处连续性的重要程度。"
                ),
                (
                    "subject_id 使用当前批次内部可复用的本地实体键，不填写数据库 ID。"
                    "整组 pages 共用 evidence_refs，这些来源必须能够支持返回的每一条记忆。"
                ),
                "格式示例（<id> 和 <local_entity_key> 只是占位符，输出时必须替换）：\n"
                "{\n"
                '  "kind": "long_term_memory_page",\n'
                '  "pages": [\n'
                "    {\n"
                '      "memory_kind": "promise",\n'
                '      "content": "我答应下次把结果告诉对方。",\n'
                '      "subject_kind": "entity",\n'
                '      "subject_id": "<local_entity_key>",\n'
                '      "confidence": 0.9,\n'
                '      "salience": 0.8\n'
                "    },\n"
                "    {\n"
                '      "memory_kind": "event",\n'
                '      "content": "我记得我们一起完成了那件事。",\n'
                '      "subject_kind": "entity",\n'
                '      "subject_id": "<local_entity_key>",\n'
                '      "confidence": 0.85,\n'
                '      "salience": 0.7\n'
                "    }\n"
                "  ],\n"
                '  "evidence_refs": ["message:<id>"]\n'
                "}",
                (
                    "如果没有任何可靠的长期记忆候选，返回 kind=no_op 和简短 reason；"
                    "不要为了填充 pages 而编造内容。"
                ),
            ]
        )
    elif node_input.node_kind == "graph_extract":
        common.extend(_MEMORY_ORGANIZE_SOURCE_GUIDANCE)
        common.extend(
            [
                (
                    "kind=graph_extraction 时，返回 entities、edges 和 evidence_refs。"
                    "entities 或 edges 至少填写一项；没有可靠内容时返回 kind=no_op。"
                ),
                (
                    "只提取当前来源中能够明确识别、以后可以复用的实体。人物、角色、地点、物品、"
                    "事件和组织都可以作为实体；普通代词、模糊指代和没有独立身份的动作不要作为实体。"
                ),
                (
                    "每个 entity 只包含 entity_id、entity_kind 和 canonical_name。"
                    "canonical_name 使用来源中的稳定称呼；同一个实体在本次输出中始终使用同一个"
                    "entity_id 和名称，不把数据库 ID 写入 entity_id。"
                ),
                (
                    "entity_id 是本次响应内部使用的本地键，必须唯一、容易辨认。"
                    "一条 edge 引用的两个实体都必须出现在本次 entities 中；"
                    "即使某个实体可能已经存在于"
                    "长期记忆，也要在本次输出中列出它，不能只引用常驻记忆里的对象。"
                ),
                (
                    "每个 edge 只包含 from_entity_id、to_entity_id、edge_kind 和 confidence。"
                    "from_entity_id 指向关系起点，to_entity_id 指向关系终点；两个实体同时出现不等于"
                    "它们存在关系。edge_kind 使用简短、稳定的关系名称，例如 participated_in、"
                    "knows 或"
                    "promised_to。"
                ),
                (
                    "同一实体或同一方向的同一种关系不要重复返回。关系必须由当前来源直接支持或能够从"
                    "当前来源明确判断；confidence 表示这条关系被当前来源支持的程度。"
                ),
                (
                    "整组 entities 和 edges 共用 evidence_refs；这些来源必须能够支持返回的"
                    "全部实体和关系。Runtime 会根据 canonical_name 查找或创建稳定实体，"
                    "模型不负责判断数据库中是否已有同一实体。"
                ),
                "格式示例（<id> 和 <local_entity_key> 只是占位符，输出时必须替换）：\n"
                "{\n"
                '  "kind": "graph_extraction",\n'
                '  "entities": [\n'
                "    {\n"
                '      "entity_id": "person:player",\n'
                '      "entity_kind": "person",\n'
                '      "canonical_name": "玩家"\n'
                "    },\n"
                "    {\n"
                '      "entity_id": "event:shared-work",\n'
                '      "entity_kind": "event",\n'
                '      "canonical_name": "共同完成的事情"\n'
                "    }\n"
                "  ],\n"
                '  "edges": [\n'
                "    {\n"
                '      "from_entity_id": "person:player",\n'
                '      "to_entity_id": "event:shared-work",\n'
                '      "edge_kind": "participated_in",\n'
                '      "confidence": 0.9\n'
                "    }\n"
                "  ],\n"
                '  "evidence_refs": ["message:<id>"]\n'
                "}",
                (
                    "不要在 graph_extraction 中填写长期记忆正文、记忆 ID、数据库实体 ID、"
                    "别名记录或提交命令。"
                ),
            ]
        )
    else:
        common.append(
            "正文保持角色第一人称，字段按照当前节点动作的结构填写；不返回 ReflectionBatch、"
            "ProposalEnvelope 或提交命令。"
        )
    return "\n".join(common)


def render_volatile_context(snapshot: ContextSnapshotV2) -> str:
    """Render all request-local state after the recent conversation tail."""

    parts = [
        render_character_state(snapshot.character_state),
        render_relationship_state(snapshot.relationship_state),
        render_situation(snapshot.situation),
    ]
    return "\n\n".join(part for part in parts if part)


def _render_memory(items: Iterable[MemoryItem], *, heading: str) -> str:
    lines = [f"- {item.summary.strip()}" for item in items if _clean(item.summary)]
    return f"{heading}\n" + "\n".join(lines) if lines else ""


def _clean(value: str) -> str:
    return value.strip()


__all__ = [
    "CHARACTER_MESSAGE_OUTPUT_SCHEMA_TEMPLATE",
    "REFLECTION_NODE_OUTPUT_SCHEMA_TEMPLATE",
    "render_active_threads",
    "render_agent_contract",
    "render_character_state",
    "render_character_profile",
    "render_character_relational_dynamics",
    "render_character_voice",
    "render_conversation_guidance",
    "render_identity_sections",
    "render_output_contract",
    "render_recalled_memory",
    "render_reflection_window",
    "render_node_input",
    "render_node_responsibility",
    "render_node_task",
    "render_prompt_section",
    "render_relationship_state",
    "render_resident_memory",
    "render_session_digest",
    "render_situation",
    "render_volatile_context",
]
