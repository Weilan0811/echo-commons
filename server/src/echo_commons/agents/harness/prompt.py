from echo_commons.agents.contracts.context import MemoryContext, SelfContext

CHARACTER_MESSAGE_OUTPUT_SCHEMA = "character_message.v1"
REFLECTION_NODE_OUTPUT_SCHEMA = "reflection_node.v1"

CHARACTER_MESSAGE_OUTPUT_SCHEMA_TEMPLATE = '{\n  "thought": "string",\n  "utterance": "string"\n}'
REFLECTION_NODE_OUTPUT_SCHEMA_TEMPLATE = (
    '{\n  "kind": "segment'
    "_summary | relations"
    "hip_reflection | sta"
    "te_reflection |\ncont"
    "inuity_digest | long"
    "_term_memory_page | "
    "graph_extraction | d"
    "iary | view_refresh "
    '| no_op",\n  "evidenc'
    'e_refs": ["message:<'
    'id>", "thought:<id>"'
    "]\n}"
)
_NODE_RESPONSIBILITIES = {
    "segment_summary_plan": (
        "你负责把当前来源段整理成角色以后能回想起"
        "来的一段经历。先看清这段时间发生了什么、"
        "角色当时有什么真实感受，再决定是否值得继"
        "续做关系或状态分析。"
    ),
    "relationship_reflect": (
        "你负责从当前来源判断关系的三个维度有没有"
        "出现可记录的变化。分别看 affecti"
        "on（好感）、trust（信任）和 at"
        "tachment（依恋），只列出材料能够"
        "支持的变化。"
    ),
    "state_reflect": (
        "你负责从当前来源判断角色自身有没有出现可"
        "记录的状态变化。只选择 physical"
        "（身体）、mood（心境）或 activ"
        "ity（活动）中的一个类别，并写下当前状"
        "态。"
    ),
    "page_compose": (
        "你负责从当前批次整理角色以后能够独立回想"
        "和再次使用的长期记忆。每条独立记忆分别写"
        "成一个 page，不把多个无关事实拼成一"
        "条。"
    ),
    "graph_extract": (
        "你负责从当前批次提取可以复用的实体和实体"
        "关系，供长期记忆图使用。实体和关系在同一"
        "个 action 中一起返回，只保留来源"
        "能够支持的内容。"
    ),
    "continuity_compress": (
        "你负责把上一条连续性摘要和当前按时间排列"
        "的段摘要，整理成一条可以继续使用的会话连"
        "续性摘要。保留重要事件、持续中的约定、未"
        "解决的事情和关系变化。"
    ),
}
_MEMORY_ORGANIZE_SOURCE_GUIDANCE = (
    (
        "memory_segment_summa"
        "ry 提供已经审核过的整体背景；conv"
        "ersation_character 表"
        "示角色说过的话；conversation"
        "_thought 表示角色当时的内心注意"
        "、感受或判断；conversation_"
        "player 只能证明玩家这样说过，不能"
        "单独证明角色已经确认或记住了这件事。"
    ),
    (
        "常驻记忆只用于理解背景和发现重复，不能填"
        "写到 evidence_refs；常驻记"
        "忆不完整也不能证明当前内容一定是新的。当"
        "前状态、关系状态和角色设定同样不能替代本"
        "次来源材料。"
    ),
)


def render_output_contract(output_schema: str) -> str:
    lines = ["请只返回一个 JSON 对象。"]
    if output_schema == CHARACTER_MESSAGE_OUTPUT_SCHEMA:
        lines.extend(
            [
                (
                    "发言对象包含 thought、utter"
                    "ance，可选 reply_to_mes"
                    "sage_id；utterance 必须"
                    "是非空字符串，thought 可以为空。"
                    "reply_to_message_id "
                    "只能填写本次输入中可见的消息标识，没有指"
                    "定回复目标时省略或填写 null。决定不"
                    '发言时，只返回 {"outcome":"'
                    'silent"}。'
                ),
                (
                    "thought 只记录角色此刻真实冒出来"
                    "的一点内心反应：正在注意什么、有什么感受"
                    "，或突然想到什么。它可以只有几个字或一句"
                    "短话；没有值得记录的念头就写空字符串。t"
                    "hought 不承担回复计划、对话分析、"
                    "模型推理或规则说明；这个字段不会展示给玩"
                    "家。"
                ),
                (
                    "utterance 只写角色此刻会发给对"
                    "方的原话，让它承担角色真正的回应。回复按"
                    "这一刻的聊天节奏来写：可以很短，也可以在"
                    "自然停顿处分成几段；换行只表示真实停顿或"
                    "本来会分开的说话，不为了显得热闹而插入，"
                    "也不因为换行额外补话。换行符在 JSON"
                    " 字符串中写作 \\n。"
                ),
                (
                    "不要输出 Markdown、解释、日志或"
                    " JSON 之外的文字，也不要谈论自己正"
                    "在执行什么要求。"
                ),
                "字段名和层级请与下面的格式示意保持一致。",
                CHARACTER_MESSAGE_OUTPUT_SCHEMA_TEMPLATE,
            ]
        )
    elif output_schema == REFLECTION_NODE_OUTPUT_SCHEMA:
        lines.extend(
            [
                (
                    "你现在做的是角色自己的回看。以角色本人的"
                    "身份阅读这些材料，把已经发生、确实感受到"
                    "或确实记住的内容整理成当前节点允许的 a"
                    "ction；不确定的地方就保留不确定。"
                ),
                (
                    "角色资料说明你是谁；当前窗口的来源材料说"
                    "明这次实际发生了什么。常驻记忆、当前状态"
                    "、关系状态和前置 Artifact 用来"
                    "理解背景；本次关系或状态的新变化，只根据"
                    "当前节点允许引用的来源判断。"
                ),
                (
                    "凡是输出摘要、记忆、日记、状态或关系视图"
                    "等正文，都从角色第一人称写成以后能够自然"
                    "回想的内容；结构化字段只使用规定的枚举、"
                    "数值和来源字符串。"
                ),
                (
                    "evidence_refs 只填写输入中"
                    "显示、且属于当前节点允许范围的来源字符串"
                    "，例如 message:<id> 或 t"
                    "hought:<id>。前置 Artif"
                    "act 可以帮助理解，但不能替代本次来源"
                    "引用。"
                ),
                (
                    "没有可以可靠归纳的内容时返回 kind="
                    "no_op 并填写 reason。来源字"
                    "符串、版本、时间、ID 和其他 Runt"
                    "ime 字段都由输入或 Runtime "
                    "提供。"
                ),
                (
                    "最后的节点说明会给出当前节点的字段结构。"
                    "只填写当前节点允许的字段，保持一个 JS"
                    "ON action；Runtime 会检"
                    "查字段名称、类型和取值。"
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


def render_expression_guidance() -> str:
    return "\n\n".join(
        [
            (
                "从角色此刻的生活、记忆、感受和正在发生的"
                "事出发回应。先看对方这一句真正说了什么，"
                "再按你自己的反应说；没有需要展开时，短短"
                "回一句也足够。话题可以停在自然的位置。"
            ),
            (
                "聊天节奏由当前内容决定。回复的长短、停顿"
                "和分段跟着你这次真正想说的量走；长消息不"
                "必全部解释，短消息也不自动变成长话题。对"
                "方的短回复有时只是短回复，先回应它本身；"
                "只有你确实从上下文感觉到别的意思时，才去"
                "猜测或追问。"
            ),
            (
                "说话只留下角色此刻会发出去的内容，让自己"
                "的反应承担对话。空泛的共情、客服式追问、"
                "重复对方的话、把日常包装成金句的比喻，都"
                "不能替代角色自己的反应。像“我懂”“我理"
                "解你的感受”“你有什么想分享的吗”“要不"
                "要我给你推荐”“需要我帮你吗”“怎么突然"
                "问这个”这类现成话术，除非角色此刻确实这"
                "样想、也确实会这样说，否则不要使用。话题"
                "可以停在任何地方，不需要每次都解释完整、"
                "总结完整或留下问题。"
            ),
            (
                "日常闲聊可以只留下即时反应；"
                "对方认真询问经历、原则或感受时，按自己的理解、性格和表达意愿说明。"
                "愿意展开时可以具体讲述，不愿意或没有相关经历时可以简短回答、保留或拒答。"
                "说到已经足够的位置就停，有真想知道的事情再问。"
                "面对认真提问，展开经历时只使用人设或实际记忆中已有的事件。"
                "为了回答问题临时补写往事不属于主动讲述生活；"
                "资料只包含共同活动时，可以讲这件事对自己的意义，不添加人物原话或新事件。"
                "可以说明自己的感受与理解，不能补出新的往事、人物原话或确定的情节；"
                "对方的提问也不能证明事情发生过。"
            ),
            (
                "角色设定只是你生活的底色，不需要每轮拿出"
                "来证明自己。只有当前话题碰到了，或者你此"
                "刻真的想到了，才自然带出自己的兴趣、经历"
                "和习惯；不要反复提同一个爱好或性格标签，"
                "也不要把个人简介背给对方听。"
            ),
            (
                "每次从当前这一刻开始说，沿用你们已经形成"
                "的相处方式，但不要照搬上一轮的开头、句式"
                "和问法。"
            ),
        ]
    )


def render_conversation_guidance() -> str:
    parts = render_expression_guidance().split("\n\n")
    parts.insert(
        2,
        "thought 是角色随手留下的私有内心"
        "，不是每轮必须完成的思考步骤。有念头就写"
        "最先冒出来的那一点，几个字、一小句都可以"
        "；没有就留空。它可以不完整、保留、犹豫，"
        "或和说出口的话不同。让它像角色当下会有的"
        "念头，不要把内容整理成分析、解释或回复方"
        "案。",
    )
    return "\n\n".join(parts)


def render_prompt_section(name: str, content: str) -> str:
    cleaned = _clean(content)
    if not cleaned:
        return ""
    return f"<{name}>\n{cleaned}\n</{name}>"


def render_node_responsibility(node_kind: str) -> str:
    return _NODE_RESPONSIBILITIES.get(
        node_kind, ("你负责完成当前固定节点声明的反思动作，只基于提供的来源作出可追溯判断。")
    )


def render_node_task(
    node_kind: str, source_refs: tuple[str, ...], last_sequence: int | None = None
) -> str:
    source_lines = "\n".join(f"- {ref}" for ref in source_refs) or "- 当前没有可引用来源"
    common = [
        "本次只返回当前节点的一个 action JSON。",
        ("evidence_refs 只填写下面列出的完整来源字符串，原样保留字符串，不添加版本。"),
        f"本节点可引用的来源：\n{source_lines}",
        (
            "省略 evidence_refs 时，R"
            "untime 会使用本节点允许范围内的默"
            "认来源；没有有效来源时返回 no_op。"
        ),
        (
            "来源版本、记录时间、状态有效期以及所有 "
            "ID 由 Runtime 补齐；节点专门"
            "要求的消息范围字段按后文填写。"
        ),
    ]
    if node_kind == "segment_summary_plan":
        common.extend(
            [
                ("返回 kind=segment_summary 时：填写 summary 和 follow_up。"),
                (
                    "summary 是角色留给自己的一小段回"
                    "忆。写这段时间真正发生的事情，以及角色当"
                    "时确实有过的感受、注意或判断；保留具体细"
                    "节和没有说完的地方。"
                ),
                (
                    "summary 覆盖本次消息与 thou"
                    "ght 能支持的内容，并以第一人称“我”"
                    "撰写。提到另一方时使用“对方”或来源中自"
                    "然的称呼；让摘要停在经历本身，不替这段经"
                    "历下关系结论。"
                ),
                (
                    "把消息和 thought 一起阅读：th"
                    "ought 帮助你找回角色当时的注意、感"
                    "受和判断，消息决定实际发生的内容。回复计"
                    "划、猜想和规则说明不写成已经发生的事情。"
                ),
                (
                    "写法可以接近：‘我那天忙到忘了吃饭，跟对"
                    "方说起这件事。对方催我先去弄点吃的，语气"
                    "有点凶，但我知道他是在关心我。’"
                ),
                (
                    "follow_up 包含 relatio"
                    "nship_reflect 和 stat"
                    "e_reflect 两个布尔值。true"
                    " 表示值得交给对应节点继续查看，不表示事"
                    "实已经改变。"
                ),
                ("如果来源不足以形成可靠摘要，返回 kind=no_op 和简短 reason。"),
            ]
        )
    elif node_kind == "relationship_reflect":
        common.extend(
            [
                ("kind=relationship_reflection 时，顶层只写 kind、evidence_refs 和 dimensions。"),
                (
                    "这一步记录关系判断本身。把理由放在 ev"
                    "idence_refs 里，dimens"
                    "ions 只保留规定的结构。"
                ),
                (
                    "dimensions 是 JSON 数组"
                    "；每一项包含 target、dimens"
                    "ion、direction、level。"
                    "target 包含 kind 和 act"
                    "or_id：kind 使用 player"
                    " 或 character，actor_i"
                    "d 使用本次材料中的玩家或角色实例标识。"
                ),
                (
                    "dimension 使用 affecti"
                    "on、trust、attachment，"
                    "同一 target 的每个维度最多出现一"
                    "次。"
                ),
                (
                    "direction 使用 positiv"
                    "e、negative 或 neutral"
                    "；positive 和 negative"
                    " 的 level 为 1 到 3，neu"
                    "tral 的 level 为 0。"
                ),
                (
                    "affection 看当下相处带来的喜欢"
                    "、亲近或愉快。一次自然、没有冲突的交流，"
                    "通常可以记录 affection 的 p"
                    "ositive level 1；只有来源"
                    "显示不愉快或疏远时，才考虑 neutra"
                    "l 或 negative。"
                ),
                (
                    "trust 看角色是否因为对方的可靠、诚"
                    "实或尊重边界而更放心交流，包括愿意让对方"
                    "知道真实感受。材料出现这些信号时再记录 "
                    "trust。"
                ),
                (
                    "attachment 看更深的信赖、对对"
                    "方本人的直接依赖或持续吸引，以及想一直保"
                    "有这段关系、想继续和对方在一起的明确感受"
                    "。普通聊天、一次关心、顺畅接话、习惯聊天"
                    "或想起对方，本身不足以支持 attach"
                    "ment。"
                ),
                (
                    "负向变化也需要来源中的具体表现，例如失望"
                    "、受伤、欺骗、越过边界或主动疏远。没有对"
                    "应信号时保持 neutral 或返回 n"
                    "o_op，不把沉默、礼貌和自己的猜想当成"
                    "变化。"
                ),
                (
                    "level 表示本次来源显示的变化幅度，"
                    "不是关系总分。一次清楚的信号通常使用 1"
                    "；2 或 3 需要当前窗口中更强或相互印"
                    "证的信号。"
                ),
                (
                    "格式示例（<id> 只是占位符，输出时必"
                    "须替换成上面列出的完整来源字符串）：\n{"
                    '\n  "kind": "relation'
                    'ship_reflection",\n  '
                    '"evidence_refs": ["m'
                    'essage:<id>"],\n  "di'
                    'mensions": [\n    {\n '
                    '     "target": {"kin'
                    'd": "player", "actor'
                    '_id": "<玩家标识>"},\n   '
                    '   "dimension": "aff'
                    'ection",\n      "dire'
                    'ction": "positive",\n'
                    '      "level": 1\n   '
                    " }\n  ]\n}"
                ),
                ("如果来源没有关系变化信号，返回 kind=no_op 和简短 reason。"),
                ("关系类型、总分、绝对数值、状态期限和数据库 ID 不属于本节点输出。"),
            ]
        )
    elif node_kind == "state_reflect":
        common.extend(
            [
                (
                    "kind=state_reflectio"
                    "n 时，选择一个 state_kind（"
                    "physical、mood、activi"
                    "ty）并填写 value。"
                ),
                (
                    "value 用角色第一人称写一句或两句具"
                    "体的当下体验，只记录来源里已经出现的当前"
                    "状态。可以参考：‘我今天一直在赶稿，脑子"
                    "有点发木，饭也差点忘了吃。’"
                ),
                (
                    "value 只写状态本身，不写对话总结或"
                    "关系结论。时间、有效期、版本和数据库 I"
                    "D 由 Runtime 管理。"
                ),
                ("如果来源没有可靠的自身状态信号，返回 kind=no_op 和简短 reason。"),
            ]
        )
    elif node_kind == "continuity_compress":
        sequence_guidance = (
            (
                f"本批次最后一条消息序号是 {last_sequence}；"
                "covers_through_sequence 必须原样填写这个数字。"
            )
            if last_sequence is not None
            else "本批次没有可用的结束消息序号，不能生成连续性摘要。"
        )
        common.extend(
            [
                (
                    "当前来源按时间顺序提供：上一条连续性摘要"
                    "（如果存在）和本批次已经审核过的段摘要。"
                    "上一条摘要只用于保持长期连续性；当前段摘"
                    "要用于补充新内容和修正已经变化的内容。"
                ),
                (
                    "kind=continuity_dige"
                    "st 时填写 content、cover"
                    "s_through_sequence 和"
                    " evidence_refs。conte"
                    "nt 用角色第一人称写成一条可以在后续对"
                    "话中直接使用的累计摘要，不要逐条复述段摘"
                    "要，也不要提到摘要、批次、序号、版本或数"
                    "据库。"
                ),
                (
                    "保留以后仍然有用的事件、约定、承诺、未解"
                    "决事项、重要偏好和关系变化。删除寒暄、重"
                    "复细节、短期情绪和对后续没有帮助的内容。"
                ),
                (
                    "只写当前材料能够支持的内容。新段摘要与上"
                    "一条摘要出现差异时，按照当前材料更新；材"
                    "料没有说明的内容保持原样或省略，不自行补"
                    "全。"
                ),
                sequence_guidance,
                (
                    "本图已经有冻结的摘要批次，只要当前材料存"
                    "在，就必须返回 continuity_d"
                    "igest。不要返回 no_op。上一条"
                    "摘要可以很短，当前批次仍然必须推进覆盖范"
                    "围。"
                ),
                "格式示例（<id> 只是占位符，输出时必须替换成输入中的完整来源字符串）：\n"
                '{\n  "kind": "continuity_digest",\n  "content": "我记得……",\n'
                f'  "covers_through_sequence": {last_sequence or 0},\n'
                '  "evidence_refs": ["summary:<id>"]\n}',
            ]
        )
    elif node_kind == "page_compose":
        common.extend(_MEMORY_ORGANIZE_SOURCE_GUIDANCE)
        common.extend(
            [
                (
                    "kind=long_term_memor"
                    "y_page 时，返回 pages 数组"
                    "；每个 pages 项都是一条可以独立检"
                    "索和回想的长期记忆。"
                ),
                (
                    "当前来源中有多个互相独立的约定、承诺、事"
                    "件或事实时，分别生成多个 pages 项"
                    "。同一件事被重复提及时合并为一个 pag"
                    "es 项；同一件事的几个细节只有在以后应"
                    "该一起回想时才合并。"
                ),
                (
                    "长期记忆必须有以后仍然有用的具体内容。普"
                    "通寒暄、一次性安排、没有得到角色支持的猜"
                    "测和只有一瞬间的情绪反应不要写入。常驻记"
                    "忆只用于理解背景和发现重复，不能填写到 "
                    "evidence_refs。"
                ),
                (
                    "每个 pages 项包含 memory_"
                    "kind、content、subject"
                    "_kind、subject_id、con"
                    "fidence 和salience。me"
                    "mory_kind 使用 fact、ev"
                    "ent、preference、promi"
                    "se、thread 或 other。"
                ),
                (
                    "content 用角色第一人称写成一条具"
                    "体记忆，只围绕一个主题。confiden"
                    "ce 表示来源对这条记忆的支持程度；sa"
                    "lience 表示它以后对保持相处连续性"
                    "的重要程度。"
                ),
                (
                    "subject_id 使用当前批次内部可"
                    "复用的本地实体键，不填写数据库 ID。整"
                    "组 pages 共用 evidence_"
                    "refs，这些来源必须能够支持返回的每一"
                    "条记忆。"
                ),
                (
                    "格式示例（<id> 和 <local_e"
                    "ntity_key> 只是占位符，输出时"
                    '必须替换）：\n{\n  "kind": "'
                    "long_term_memory_pag"
                    'e",\n  "pages": [\n   '
                    ' {\n      "memory_kin'
                    'd": "promise",\n     '
                    ' "content": "我答应下次把结'
                    '果告诉对方。",\n      "subj'
                    'ect_kind": "entity",'
                    '\n      "subject_id":'
                    ' "<local_entity_key>'
                    '",\n      "confidence'
                    '": 0.9,\n      "salie'
                    'nce": 0.8\n    },\n   '
                    ' {\n      "memory_kin'
                    'd": "event",\n      "'
                    'content": "我记得我们一起完成'
                    '了那件事。",\n      "subje'
                    'ct_kind": "entity",\n'
                    '      "subject_id": '
                    '"<local_entity_key>"'
                    ',\n      "confidence"'
                    ': 0.85,\n      "salie'
                    'nce": 0.7\n    }\n  ],'
                    '\n  "evidence_refs": '
                    '["message:<id>"]\n}'
                ),
                (
                    "如果没有任何可靠的长期记忆候选，返回 k"
                    "ind=no_op 和简短 reason"
                    "；不要为了填充 pages 而编造内容。"
                ),
            ]
        )
    elif node_kind == "graph_extract":
        common.extend(_MEMORY_ORGANIZE_SOURCE_GUIDANCE)
        common.extend(
            [
                (
                    "kind=graph_extractio"
                    "n 时，返回 entities、edge"
                    "s 和 evidence_refs。en"
                    "tities 或 edges 至少填写一"
                    "项；没有可靠内容时返回 kind=no_"
                    "op。"
                ),
                (
                    "只提取当前来源中能够明确识别、以后可以复"
                    "用的实体。人物、角色、地点、物品、事件和"
                    "组织都可以作为实体；普通代词、模糊指代和"
                    "没有独立身份的动作不要作为实体。"
                ),
                (
                    "每个 entity 只包含 entity"
                    "_id、entity_kind 和 ca"
                    "nonical_name。canonic"
                    "al_name 使用来源中的稳定称呼；同"
                    "一个实体在本次输出中始终使用同一个ent"
                    "ity_id 和名称，不把数据库 ID "
                    "写入 entity_id。"
                ),
                (
                    "entity_id 是本次响应内部使用的"
                    "本地键，必须唯一、容易辨认。一条 edg"
                    "e 引用的两个实体都必须出现在本次 en"
                    "tities 中；即使某个实体可能已经存"
                    "在于长期记忆，也要在本次输出中列出它，不"
                    "能只引用常驻记忆里的对象。"
                ),
                (
                    "每个 edge 只包含 from_ent"
                    "ity_id、to_entity_id、"
                    "edge_kind 和 confiden"
                    "ce。from_entity_id 指向"
                    "关系起点，to_entity_id 指向"
                    "关系终点；两个实体同时出现不等于它们存在"
                    "关系。edge_kind 使用简短、稳定"
                    "的关系名称，例如 participate"
                    "d_in、knows 或promised"
                    "_to。"
                ),
                (
                    "同一实体或同一方向的同一种关系不要重复返"
                    "回。关系必须由当前来源直接支持或能够从当"
                    "前来源明确判断；confidence 表"
                    "示这条关系被当前来源支持的程度。"
                ),
                (
                    "整组 entities 和 edges "
                    "共用 evidence_refs；这些来"
                    "源必须能够支持返回的全部实体和关系。Ru"
                    "ntime 会根据 canonical_"
                    "name 查找或创建稳定实体，模型不负责"
                    "判断数据库中是否已有同一实体。"
                ),
                (
                    "格式示例（<id> 和 <local_e"
                    "ntity_key> 只是占位符，输出时"
                    '必须替换）：\n{\n  "kind": "'
                    'graph_extraction",\n '
                    ' "entities": [\n    {'
                    '\n      "entity_id": '
                    '"person:player",\n   '
                    '   "entity_kind": "p'
                    'erson",\n      "canon'
                    'ical_name": "玩家"\n   '
                    ' },\n    {\n      "ent'
                    'ity_id": "event:shar'
                    'ed-work",\n      "ent'
                    'ity_kind": "event",\n'
                    '      "canonical_nam'
                    'e": "共同完成的事情"\n    }\n'
                    '  ],\n  "edges": [\n  '
                    '  {\n      "from_enti'
                    'ty_id": "person:play'
                    'er",\n      "to_entit'
                    'y_id": "event:shared'
                    '-work",\n      "edge_'
                    'kind": "participated'
                    '_in",\n      "confide'
                    'nce": 0.9\n    }\n  ],'
                    '\n  "evidence_refs": '
                    '["message:<id>"]\n}'
                ),
                (
                    "不要在 graph_extraction"
                    " 中填写长期记忆正文、记忆 ID、数据库"
                    "实体 ID、别名记录或提交命令。"
                ),
            ]
        )
    else:
        common.append(
            "正文保持角色第一人称，字段按照当前节点动"
            "作的结构填写；不返回 Reflectio"
            "nBatch、ProposalEnvel"
            "ope 或提交命令。"
        )
    return "\n".join(common)


def _clean(value: str) -> str:
    return value.strip()


def render_reflection_source_introduction() -> str:
    return (
        "这是本次反思可以使用的上下文。下面的来源材料记录了当前窗口实际发生的内容；"
        "状态和关系信息只帮助你理解角色当时所处的位置。"
    )


def render_persona(
    agent_contract: str, profile: str, relational_dynamics: str, voice: str | None = None
) -> tuple[tuple[str, str], ...]:
    shared = "全部输出都以角色本人的身份理解和表达，始终遵循角色的身份、记忆、能力与表达规则。"
    sections = (
        ("agent_contract", shared + "\n\n" + agent_contract.strip()),
        ("character_profile", profile),
        ("character_relational_dynamics", relational_dynamics),
    )
    return (*sections, ("character_voice", voice)) if voice is not None else sections


def render_identity(identity: SelfContext, *, include_voice: bool) -> tuple[tuple[str, str], ...]:
    return render_persona(
        identity.agent_contract,
        identity.profile,
        identity.relational_dynamics,
        identity.voice if include_voice else None,
    )


def render_state(identity: SelfContext) -> str:
    sentences = [
        {
            "available": "你现在有空，可以自然地回应对方。",
            "busy": "你手头还有自己的事情，但能分一点心思回应对方。",
            "offline": "你现在不在线，回应会显得断断续续。",
        }[identity.availability]
    ]
    for value, template in (
        (identity.physical_state, "身体状况是{}。"),
        (identity.mood, "心情是{}。"),
        (identity.activity, "手头正在做的是{}。"),
    ):
        if value.strip():
            sentences.append(template.format(value))
    return "你此刻的状态：\n" + " ".join(sentences)


def render_relationships(identity: SelfContext) -> str:
    descriptions = {
        "stranger": "你和对方目前还是陌生人。",
        "acquaintance": "你和对方已经是熟人。",
        "friend": "你和对方已经是朋友。",
    }
    return "\n\n".join(
        f"关系目标：{relation.target_name}（{relation.target.kind.value}:{relation.target.actor_id}）\n"
        + "你和对方现在的相处：\n"
        + " ".join(
            part
            for part in (descriptions[relation.relationship_type], relation.attitude.strip())
            if part
        )
        for relation in identity.relationships
    )


def render_memory(memory: MemoryContext) -> str:
    resident = render_memory_items(memory.resident, heading="你一直记得的一些事情：")
    digest = (
        "你对前面这段相处还留着这样的印象：\n" + memory.session_digest.strip()
        if memory.session_digest.strip()
        else ""
    )
    summaries = tuple("近期消息段摘要\n" + item.content for item in memory.segment_summaries)
    return "\n\n".join(part for part in (resident, digest, *summaries) if part)


def render_memory_items(items, *, heading: str) -> str:
    lines = [f"- {item.content.strip()}" for item in items if item.content.strip()]
    return heading + "\n" + "\n".join(lines) if lines else ""
