# 角色提示契约与完整表达规则

## 1. 提示资源与组装职责

固定提示正文保存在 `src/echo_commons/resources/prompts/`。本文件说明资源分工、输入与输出约束；修改提示文字直接编辑资源，避免文档和代码各维护一份正文。资源随安装包发布，运行进程缓存读取结果，修改后重启进程。

| 代码 | 职责 |
|---|---|
| conversations/tasks/prompt.py | 组合聊天要求、人设、状态、关系、记忆和按顺序排列的消息 |
| reflection/tasks/prompt.py | 组合反思要求、人设、背景、材料情境、节点材料、阅读范围、前驱产物和当前节点任务 |
| agents/harness/prompt.py | 读取资源，提供共同人设、状态、关系与记忆格式化函数 |

Harness（模型执行循环）负责模型请求、工具、格式修正和预算。它接收业务组装好的消息，不选择反思节点或业务材料。实际执行入口见 [角色 Agent 与模型](agents-and-models.md)。

## 2. 对话输出规则

完整正文与示例见 [conversation/output.md](../../src/echo_commons/resources/prompts/conversation/output.md)。对话使用 `character_message.v1`，支持发言及明确沉默；`thought` 是自身私有内心，`utterance` 是公开发言，回复目标只能使用可见消息标识。

输出字段、枚举和限制以代码中的正式输出类型为准。执行循环从 OutputRegistry（输出契约登记表）生成结构说明，资源解释字段含义和表达要求。

## 3. 对话表达指导

[common/expression.md](../../src/echo_commons/resources/prompts/common/expression.md) 定义共同自然表达，用于聊天与人物采访；[conversation/guidance.md](../../src/echo_commons/resources/prompts/conversation/guidance.md) 补充聊天中的 Thought（内心记录）要求和状态、关系、记忆的使用方式。

## 4. 身份规则的共同说明

`render_persona` 使用任务绑定的 agent-contract、profile、relational-dynamics 和可选 voice 正文。聊天、认知及核心表达使用人物语气；事实提取按实际身份保存信息。各节点选择见 [输入矩阵](reflection/execution-model.md#2-节点输入与引用资格)，身份正文不复制到任务提示资源。

## 5. 共同反思输出规则

共同资源 `reflection/common.md` 定义材料性质、知识边界和输出纪律，完整契约见 [共同反思正文](#共同反思正文)。事实记录清楚交代谁表达或经历了什么；认知记录说明角色怎样理解；段与连续摘要压缩经历以维持交流。正文视角由节点决定，事实提取不强制使用第一人称。人物背景、旧认识与常驻视图不能补写原始来源缺少的经历、动机或因果。

## 6. 节点职责与资源

每个模型节点的职责、判断要求及输出示例放在同一份资源中，由 ReflectionNodeDefinition（固定节点定义）指定路径。规划与聚合节点由程序执行，不读取模型提示。

| 节点 | 完整提示资源 |
|---|---|
| segment_summary_plan | [段摘要与后续分析选择](../../src/echo_commons/resources/prompts/reflection/nodes/segment_summary_plan.md) |
| relationship_reflect | [关系变化判断](../../src/echo_commons/resources/prompts/reflection/nodes/relationship_reflect.md) |
| state_reflect | [状态变化判断](../../src/echo_commons/resources/prompts/reflection/nodes/state_reflect.md) |
| continuity_compress | [连续性压缩](../../src/echo_commons/resources/prompts/reflection/nodes/continuity_compress.md) |
| fact_extract | `reflection/nodes/fact_extract.md`；[事实提取完整正文](#fact_extract) |
| cognition_reflect | `reflection/nodes/cognition_reflect.md`；[认知形成完整正文](#cognition_reflect) |
| core_memory_view | [核心记忆认识](../../src/echo_commons/resources/prompts/reflection/nodes/core_memory_view.md) |
| state_summary_view | [状态概括](../../src/echo_commons/resources/prompts/reflection/nodes/state_summary_view.md) |
| relationship_attitude_view | [关系态度](../../src/echo_commons/resources/prompts/reflection/nodes/relationship_attitude_view.md) |

## 7. 节点共同任务说明

共同资源 `reflection/task.md` 声明实际允许引用、更新范围和程序负责的字段，完整契约见 [共同任务正文](#共同任务正文)。代码填入本次实际允许的材料编号，来源覆盖由程序维护。变量使用标准库 `string.Template` 替换，材料正文不作为模板解释。

## 8. 摘要、状态与关系的节点细则

`reflection_node.v6` 使用简单材料和人物编号，程序保存正式身份、版本和精确覆盖。完整提示以所属资源为准：

| 节点 | 输出与提示 |
|---|---|
| segment_summary_plan | 单份 summary 与 follow_up；目标分别填写人物编号及新材料编号。[完整提示](../../src/echo_commons/resources/prompts/reflection/nodes/segment_summary_plan.md) |
| relationship_reflect | 各维度填写人物、方向、幅度、类别及分别依据；同一人物各维度使用同一证据类别。[完整提示](../../src/echo_commons/resources/prompts/reflection/nodes/relationship_reflect.md) |
| state_reflect | 状态类别、正文与实际新材料编号。[完整提示](../../src/echo_commons/resources/prompts/reflection/nodes/state_reflect.md) |
| continuity_compress | 单份 content，程序维护累计覆盖；有正式摘要材料时必须生成正文。[完整提示](../../src/echo_commons/resources/prompts/reflection/nodes/continuity_compress.md) |

段摘要、关系及状态节点允许有效 no_op，模型只填写 kind 与 reason。摘要无正文时仍由程序登记处理范围；连续压缩对仅含空段的范围直接推进消费，不调用模型。编号不能引用只读前情产生新变化；关系目标的实际依据资格在节点审核中检查。同一人物证据类别不一致时直接进入本次输出修正，不能等到最终事实提交才失败。

## 9. 材料情境与来源解释

| 来源情境 | 提示资源与含义 |
|---|---|
| 对话段、摘要批次 | [dialogue.md](../../src/echo_commons/resources/prompts/reflection/materials/dialogue.md)：消息说明实际发言，Thought 表达当时内心，摘要负责压缩和定位 |
| 作者材料批次 | [author.md](../../src/echo_commons/resources/prompts/reflection/materials/author.md)：区分过去经历、习惯、设定和采访观点 |
| 正式变化批次 | `reflection/materials/facts.md`：区分状态、关系、MemoryFact 与 MemoryCognition，视图仅表达已保存内容 |

角色创作继续使用独立的 `resources/authoring/` 四套提示和 AuthoringAgent（创作智能体）。创作确认保存人物资源；实例创建后按记忆模式初始化，完整模式的作者材料整理与核心认识生成复用正式反思流程。

## 10. 上下文段落与文字模板

段落使用 `<段落名>\n正文\n</段落名>` 包装，相邻段落以两个换行分隔。身份段落的标签为 `agent_contract`、`character_profile`、`character_relational_dynamics`、`character_voice`。其他段落的顺序与标签见 [提示组装顺序](agents-and-models.md#2-提示与输出)。可选内容为空时省略对应段落；来源身份和文字使用冻结输入中的真实值。

### 常驻记忆、检索记忆与连续性摘要

常驻记忆使用以下标题，每条记忆随后写成 `- {summary}`，各条之间换行：

```text
你一直记得的一些事情：
```

检索记忆同样逐条列出，标题为：

```text
此刻从更远处浮现出来的一些记忆：
```

连续性摘要使用以下模板：

```text
你对前面这段相处还留着这样的印象：
{content}
```

核心记忆以 `核心记忆` 为标题，下一行加入一份正文，可以包含自然段落。核心刷新通过 `reading_scope` 提供本轮记录、未读数量、完整性、来源状态和旧正文，范围信息不作为证据。正式类型、版本和成功读取进度留在运行层。自身状态摘要以 `当前状态摘要` 为标题，下一行加入正文；每份段摘要以 `近期消息段摘要` 为标题，下一行加入正文。同一段落包含多份内容时，以两个换行分隔。

按需检索的长期材料区分“事实记录”和“角色认知”，分别保留陈述者或认识对象、来源性质及必要时间。具体经过不能因进入角色上下文变成确定的亲身回忆，旧推断不能因为多次出现在摘要中加强确定程度。玩家交流使用自然称呼和表达，不向玩家讲述内部记录类型。

### 未完成事项

标题为 `你心里还挂着这些事情：`。每条事项独占一行，waiting（等待回应）使用 `- 这件事还在等一个回应：{summary}`，resolved（已经解决）使用 `- 这件事已经暂时告一段落：{summary}`，其他状态使用 `- {summary}`。

### 自身状态

标题为 `你此刻的状态：`，下一行按可用状态、身体、心情、当前活动的顺序组合句子，以空格分隔。缺少身体、心情或活动内容时省略对应句子：

```text
身体状况是{physical_condition}。
心情是{mood}。
手头正在做的是{current_activity}。
```

| 可用状态 | 句子 |
|---|---|
| available | 你现在有空，可以自然地回应对方。 |
| busy | 你手头还有自己的事情，但能分一点心思回应对方。 |
| offline | 你现在不在线，回应会显得断断续续。 |

### 关系状态

按关系目标分别组织段落，先提供该目标的 kind、actor_id 和显示名称。正文标题为 `你和对方现在的相处：`；下一行先填写关系类型对应句子，再以空格连接该目标的实际态度正文。

| 关系类型 | 句子 |
|---|---|
| stranger | 目前还不熟，没有具体相处印象。 |
| acquaintance | 你和对方已经是熟人。 |
| friend | 你和对方已经是朋友。 |

### 情境观察

标题为 `眼前的情境：`。存在环境描述时加入 `周围给你的感觉是：{ambient_summary}`；存在观察事件时加入 `你注意到：`，每个事件随后写成 `- {event}`。各部分以换行分隔，最后加入实际存在的不确定性说明。缺少某项内容时省略该项。

### 反思材料

完整快照保留正式身份、版本、精确受众和各场景序号。模型材料按场景分组，各组说明群聊或私人交流；组内按时间提供简短时间、人物称呼、正文及材料编号。必要回复指向材料编号，私有受众标记在材料旁。只读前情明确标记，不能成为新变化依据。

关系和状态节点另外读取前驱回忆正文作为背景。人物表使用本次人物编号，同名人物仍按编号区分；关系节点只提供计划允许的目标及新依据。任务说明和实际 JSON Schema 由所属节点定义，源版本与正式身份由程序转换保存。

### 历史阅读说明

当前会话的 user 与 assistant 消息按顺序提供。其他场景逐组作为 system 背景，附自然名称、私人范围和紧凑时间，不要求角色逐条回答其他场景。自身 Thought 与对应发言一起出现并一起裁剪；当前触发与根玩家输入在共同说明中明确指定。

场景标签只解释交流在哪里发生，材料编号只定位本次证据，两者不能混用。读取、冻结和预算见 [角色上下文](perspective-and-context.md)。

## 11. 多角色与活动输入约束

| 信息或字段 | 用途与约束 |
|---|---|
| 角色实例、社群、消息发送者 | 明确本次观察者和实际交流对象；其他角色的私有信息不进入输入 |
| thought、utterance、reply_to_message_id | 发言结构与表达规则由第 2 节定义；回复目标必须是可见消息 |
| outcome=silent | 明确结束本次对话任务，不创建公开发言 |
| 关系 target | 每项变化指定真实目标；同一目标每维最多一次，判断及幅度使用第 8 节的三维规则 |
| 实例自身状态与有向关系 | 自身状态属于当前实例，关系按观察者和目标分别提供 |
| 活动棋局、私有观察、允许动作 | 由未来 ActivityTask 的专用输入和动作契约提供，具体边界见 [活动接入](activity-integration.md) |

标识使用本次真实输入中的值。NoOp 的许可按流程区分；视图以第一人称选择已有记录表达，核心支持引用包含实际记录类型、编号和版本。事实使用清楚的归属与来源性质，认知正文说明当时感受、后来理解及必要的不确定性。日记遵守自己的来源与输出契约。

## 12. 正式记忆工具的文字与协议

工具名为 memory_search（记忆搜索）。工具定义的 description（说明文字）为：

在角色可见的长期记忆和相关对话中检索有限的记忆线索。

query 参数的 description 为：

想回想的主题、人物或事件

query 为非空字符串，上限 256 个字符；limit 为 1—5 的整数，默认 5。多角色扩展的社群、实例、会话上限和观察时间由任务授权提供，不加入模型可自由选择的参数。

工具返回 retrievalKind 和 results；结果保存 sourceKind、sourceId、sourceRef、contentVersion、retrievalPolicyVersion、summary、context（场景及范围），以及适用的 memoryId、occurredAtUtc。长期结果按真实记录类型保留事实或认知性质和必要时间，经过明确转换进入模型观察。执行外壳保存 tool、callId、ok、output，以及适用的 errorCode、progressed、newItemCount、noProgressStreak；权限来自任务，不由模型参数选择。检索与资格规则见 [记忆](memory.md#6-搜索与重建)。

## 13. 格式修正与任务审核提示

| 错误码 | 提示正文 |
|---|---|
| invalid_model_output | 请只返回符合输出 Contract 的 JSON 对象，并补全所有必需字段。 |
| output_truncated | 请完整返回输出 Contract 要求的 JSON 对象。 |
| invalid_query | 请把 memory_search 的 query 改为非空字符串。 |
| query_too_long | 请缩短 memory_search 的 query。 |
| invalid_limit | 请把 memory_search 的 limit 改为 1 到 5 之间的整数。 |

格式修正外壳为 `上一轮输出未通过校验。错误码：{error_code}。{hint}`。错误码和对应 hint 由运行层填写。

任务审核发现以下问题时，恢复请求使用对应提示；是否再次执行由 [错误与恢复策略](errors-and-recovery.md) 决定。

| 情况 | 提示正文 |
|---|---|
| thought 超长 | 请缩短 thought，使其符合长度限制。 |
| utterance 为空 | 请生成非空的 utterance 字段。 |
| utterance 超长 | 请缩短 utterance，使其符合长度限制。 |

反思节点审核使用以下固定提示。每次提示只加入新的调用，合法材料继续来自冻结输入。

| 错误码 | 提示正文 |
|---|---|
| reflection_output_too_long | 请缩短本节点输出的 JSON，使其符合长度限制。 |
| reflection_summary_required | 请按照本节点契约生成段摘要，本节点需要正式摘要产物。 |
| reflection_digest_required | 请按照本节点契约生成连续性摘要，本节点需要正式摘要产物。 |
| reflection_evidence_mismatch | 请让顶层 evidence_refs 等于各项引用的去重合集。 |
| reflection_evidence_missing | 请为每项事实或认知填写真正支持它的允许来源。 |
| reflection_evidence_unknown | 请仅引用本次输入允许的 evidence_refs。 |
| reflection_relationship_description_required | 当前目标已有有效证据且描述为空，请依据本次材料生成有限的首次关系描述，不能返回 no_op。 |
| reflection_relationship_attitude_too_long | 关系描述超过本次 content 字符上限，请保留有依据的认识，缩短正文，不填写分数。 |
| reflection_view_target_unknown | 请使用当前正式关系材料中提供的目标 kind 与 actor_id。 |
| reflection_relationship_target_unknown | 请仅选择本次输入允许的关系目标。 |
| reflection_relationship_evidence_mismatch | 请为各人物分别引用其允许的新材料，不能使用另一人的依据或只读前情。 |
| reflection_action_mismatch | 请使用本节点允许的行动类型。 |

工具连续无进展时，按执行循环的计数结果使用以下文字：

```text
工具 {tool_name} 本次没有提供新材料，可以改变查询方式，也可以根据现有材料直接回答。
```

达到无进展次数上限并停用工具时：

```text
工具 {tool_name} 已连续多次没有提供新材料。本次运行不会再提供该工具，请根据现有材料回答。
```

工具参数修正以 `工具参数需要修正。` 开头，每项错误写成 `错误码：{error_code}。{hint}`，多项之间以 `；` 分隔。没有具体修正信息时使用 `请重新生成符合输出要求的内容。`。动态位置填写本次实际工具名、错误码及上表对应文字。

## 14. 情境提示设计

角色提示由共同身份与事实规则、人物正文、任务输出契约、情境说明及实际来源材料组成。共同规则定义人物立场与知识边界，情境说明定义正在进行的交流。各情境使用同一份共同规则与人物正文，任务格式按执行目的选择。

| 情境 | 输入来源 | 表达要求 | 输出与状态边界 |
|---|---|---|---|
| 日常聊天 | 实例人设、可见历史、允许读取的状态关系与记忆 | 随当前话题自然回应，保留短答、停顿与沉默 | 对话输出契约；正式审核后写入发言和自身内心记录 |
| 认真提问 | 聊天的实际上下文及对方问题 | 根据问题与自己的意愿展开，保持原有语气和边界 | 沿用聊天契约与来源范围 |
| 人物采访 | 作者确认的三份正文、故事、选定问题和已有回答 | 尽量坦诚地说清生活与经过，保留人物口吻和明确限制 | 专用问答契约；新增过去独立作为建议，保存候选，不写入会话及实例状态 |

日常聊天和认真提问通过共同表达指导适应话题，使用同一套对话流程。采访采用 [专属完整情景提示](../../src/echo_commons/resources/authoring/interview.md)，说明坦诚回答、普通偏好创作、已确认经历及新增过去建议的边界；随后使用 [材料检查提示](../../src/echo_commons/resources/authoring/interview-review.md) 核对草稿，人物正文在这一步作为资料输入。

render_persona 负责人物正文组装；render_expression_guidance 及日常 agent-contract 用于聊天，聊天额外保留 thought 说明。采访只复用 profile、voice 与 relational_dynamics 的组装，另外提供名字、基础描述、作者故事和选题，不注入日常回避与补写往事的指导。草稿不具有社群角色身份，不注入虚构成员、即时状态或关系。新候选保存版本 2.0 的完整实际提示，执行读取冻结正文。问答、新背景建议及三文档校准的边界由 [人物创作设计](custom-character-authoring.md#4-采访与实际角色扮演的共同部分) 定义。

扩展情境时说明实际目的、来源、表达方式和输出契约，复用共同人物规则。知识、权限和状态写入由任务规则决定；情境说明不改变这些边界。

## 15. 群聊来源与连续接话

当前会话的历史与输入按序号排列，每条展示简短时间、发送者称呼和正文。实际提及附上对象称呼，回复附上原文短引用；同名发送者、提及对象及回复对象使用共同的区分称呼。提及名称在准备消息快照时读取，简单模式同样保留。模型按交流经过理解话题，触发来源及根玩家来源编号留在快照与调度记录中。指导允许回应另一名角色、自然附和、追问和合法沉默。程序排序、深度和剩余额度留在诊断，不进入角色表达要求。正式组装顺序见 [Agent 与模型](agents-and-models.md#2-提示与输出)，输出契约保持不变。

## 16. 反思提示组装

`reflection/common.md` → 节点所需人物正文 → 允许的状态、关系及旧记忆背景 → `materials/*.md` 与本批来源 → 可选 `reading_scope` 和已审核前驱 → `task.md` → `nodes/*.md`。材料和允许引用先由所属服务冻结，提示组装不导入存储模块。

共同资源定义信息性质和输出纪律，来源资源解释本批材料，节点正文负责选材、操作和视角。事实节点忠实保存信息，认知节点形成或更新认识，核心和关系节点选择已有内容表达。创作提示继续独立维护。

## 17. 长期整理与共同提示的完整正文

长期整理的模型输出为 `memory_organize.v5`：每项只填写 `content`（正文）和 `sources`（材料编号）。认识刷新采用 `view_refresh.v3`：只填写正文和材料编号。fact_review 使用独立的 reflection_fact_review.v2 契约，模型仅填写候选编号、add／support／correct 和旧事实材料编号。程序维护正式来源、身份、版本、时间及支持关系。无变化分别使用空 `items` 或空正文，程序转换为内部无变化结果。

事实与认知由所属节点区分，陈述归属、计划和不确定性保留在正文中，不设置细分类别。材料编号只在本次输入有效，程序将它转换为冻结的来源或记录引用。事实提取投影保留候选正文；审核模型选择简单处理动作，程序再转换为领域操作并校验。

### fact_extract

```text
从本批原始消息或作者材料里，提取角色以后仍可能用得上的事实。每项只写一件完整的事情，交代清楚相关的人、事情和必要条件，让它离开这段聊天也能读懂。普通寒暄、重复接话和临时动作，没有后续意义时可以略去。

谁说过什么，按谁的说法保存。“他说已经做完”保留说话者，不能替他证明动作完成。自述、转述、计划和约定保持原来的性质；未知时间保持未知，材料里的否定和条件不能省略。背景人物沿用原文称呼，不替他们创建成员身份。

消息没有直接表达的心情、判断和动机不写进事实。人物档案只帮助理解称呼，不替消息补出内心；看到一句关心的话，可以记录那句话，不能断定说话者真的担心或只是客气。

人物档案帮助认清称呼。每项事实必须引用原始消息或作者材料的编号。已有事实与本项有关时，可以同时引用其材料编号，程序负责判断保存关系；只引用旧事实时保持旧记录，不新增内容。旧认知不参与事实提取。

只返回一个包含 items 列表的 JSON 对象。每项只有 content、sources 两个字段。content 是事实正文，sources 是实际支持本项的材料编号数组，例如 [2, 5]。重复编号只写一次，不填写人物编号、日期字段、版本、操作或更新目标。需要保留的时间写在正文里，且必须来自材料。

没有值得保留的事实时返回 {"items":[]}。返回前检查是否补出了材料没有的动作、动机或因果，以及是否把短时状态写成长期属性。
```

### fact_review

```text
逐项比较本批候选事实与提供的旧事实，为每个候选选择 add、support 或 correct。每个候选只处理一次；target 使用旧事实的材料编号，不填写正式身份或版本。

add：新的事件、新时期的状态、新的说法，或者没有可以确认的同一项旧事实。target 为 null。
support：新依据再次支持同一事实，人物、时间、条件、说话者和含义一致，措辞可以不同。target 为对应旧事实编号。
例如旧事实为“小明约好周二去取书”，新候选为“小明再次确认周二去取书，约定没变”，选择 support。再次确认、换一种措辞，不会自动形成新的事件。
correct：本批新原始依据明确说明旧记录的提取或归属存在错误，候选正文足以替代该旧记录。target 为对应旧事实编号。保留历史发言：A曾说某件事这项事实，不会因为后来有人反驳就失效。计划改变、偏好变化和不同人的相反说法分别新增。人物相信了错误说法，由后续认知节点更新认识。

相似主题不能直接说明同一事实，否定、条件、时间或对象不同需要分别考虑。后来发言也不自动证明旧记录错误。证据不足时选择 add。每项旧事实在本批最多处理一次；其余独立候选选择 add。

只返回 {"items":[{"item":1,"action":"add","target":null}]}。item 是候选编号，action 使用 add、support、correct，target 是旧事实材料编号或 null。覆盖所有候选，不重写候选正文，不补充外部知识。
```

### cognition_reflect

```text
阅读本批审核后的事实、自己的内心原文和允许引用的旧记忆，看看角色形成了哪些值得留下的认识。事实无需逐条配上一条感想，换一种说法复述事实也没有必要保存。

每项围绕一个具体的人或事项，用角色自然的第一人称写出想法。说清正在理解谁、什么事情让自己有了这样的认识。用具体称呼，避免离开这段材料就分不清“他”“她”指谁。人物背景影响理解角度和口吻，不能补出新的外部事件。

当时已有的感受按自己的内心原文保存来源，后来形成的判断写清由来。对方的说法、自己的期待和未知动机各自说清楚；现在的解释不能写成当时已经有的念头。需要表达不确定性时直接在正文中说明，不填写种类或置信分数。

sources 填写实际依据的材料编号。审核后的事实、允许的旧事实，以及自己的内心或作者原文都可以提供依据。旧认知用来比较，不能独自证明新认识；只有旧认知支持的改写由程序略过，已有认识仍成立且没有新内容时也略过。一项旧认知仅由本批一条新认识承接，且有新的有效依据时，程序保存前后版本；同一旧认知涉及几条新认识，或一条新认识比较多项旧认知时，程序分别保存新认识，保留旧记录。

一次相处不自动说明永久性格，也不用变成以后每次都得遵守的交往规则。可以保留有限的印象、疑问和感受，不强行写人生总结，不反复加“保持边界”或逐句免责。不修改关系分数、当前状态、人设、别人的记忆或活动结果。

只返回一个包含 items 列表的 JSON 对象，每项只有 content、sources 两个字段。content 是认识正文，sources 是依据编号数组，例如 [1, 4]。不填写正式编号、版本、操作、更新目标或时间字段。没有值得保存的新认识时返回 {"items":[]}。
```

### 共同反思正文

```text
完成当前节点规定的整理任务。原始消息、作者材料、自身内心、摘要、正式记录和旧认识保留各自的材料性质，不能因为进入本次输入就获得相同的事实资格。

事实提取忠实交代谁表达或经历了什么。认知记录说明角色怎样理解。段与连续摘要压缩经历以维持交流连续性；状态、关系和核心视图表达所属节点允许使用的材料。正文视角和写法遵守当前节点，不用共同规则强制所有事实写成第一人称。

名字、正式身份、时间、否定和条件按实际材料保存。未知保持未知，陈述保留说话者，判断保留理解者；人设和语气不能补写经历、动机或因果。文字按具体内容展开，删除重复评价和没有信息的总结，不要求统一长度或结论。

字段、引用资格和输出上限以本节点的完整说明及实际 JSON Schema 为准。每项记忆填写自己的材料编号，程序分别保存依据；旧背景与常驻视图不自动成为本次证据。

正式编号、版本、来源覆盖、状态修改和保存由运行编排层负责。缺少可靠内容时只在节点允许的情况下返回 no_op；需要推进摘要覆盖时返回其规定的摘要动作。

只返回当前节点允许的一个 JSON action，不附编辑过程、日志、额外解释或提交命令。
```

### 共同任务正文

```text
完成当前节点说明中的任务，只返回实际输出契约允许的一个 action JSON。

本节点允许引用的来源标签：
$source_refs

来源标签原样复制。引用位置按当前节点 Schema 填写。

旧记录、前驱事实候选和主体身份的引用资格由本节点提供的清单决定。局部引用不等于正式存储编号，程序负责转换及审核。

正文遵守当前节点的材料性质、视角、用途和预算。处理动作只填写节点明确要求的简单字段，不输出 ReflectionBatch、ProposalEnvelope 或额外说明。
```
