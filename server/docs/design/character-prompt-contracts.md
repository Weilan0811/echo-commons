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

共同资源 `reflection/task.md` 声明实际允许引用、更新范围和程序负责的字段，完整契约见 [共同任务正文](#共同任务正文)。代码填入实际允许来源；连续性节点还填入本批结束消息序号。变量使用标准库 `string.Template` 替换，材料正文不作为模板解释。

## 8. 摘要、状态与关系的节点细则

段摘要、关系、状态和连续性的完整要求见第 6 节对应资源。长期事实与认知使用本文件的独立正文。三个常驻表达节点也各有自己的完整提示，选材规则见 [认识刷新](reflection/view-refresh.md)。

关系变化与关系态度共同读取 [三维关系含义](../../src/echo_commons/resources/prompts/common/relationship-dimensions.md)。关系变化判断本次方向与幅度；关系态度理解已经保存的关系数值与历史证据，不修改分数。该节点同时读取人物 voice；当前目标身份、自然称呼、首次描述标记、原描述和正文读取状态来自冻结正式材料，多人段来源额外提供目标本人的实际发言。

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

反思窗口以以下正文开始：

```text
这是本次反思可以使用的上下文。下面的来源材料记录了当前窗口实际发生的内容；状态和关系信息只帮助你理解角色当时所处的位置。
```

存在消息序号时随后加入：

```text
消息范围：
起始消息序号：{first_sequence}
结束消息序号：{last_sequence}
```

状态和关系按节点输入矩阵选择，再加入 `本次可以引用的来源材料：`。每份材料使用以下模板，材料之间以两个换行分隔；没有发生时间时省略括号及其内容：

```text
[{source_ref}] {source_kind} ({occurred_at_utc})
{content}
```

图节点的材料段落先列 `可引用来源材料：`，随后列 `仅作背景的常驻记忆（不要填写到 evidence_refs）：`；没有对应材料时省略该部分。这些材料按 `[{source_ref}] {source_kind}`、换行及正文组织，材料之间以两个换行分隔。节点任务说明再列出第 7 节的允许来源字符串。前驱产物另列为分析背景，不能混入可引用材料列表。

### 历史阅读说明

conversation_history 段落使用以下正文：

```text
下面的 user 和 assistant 消息是已经发生的对话。assistant 消息中的 thought 是角色当时留下的私有内心片段；最后的 user 消息是本次需要回应的内容。
```

本轮有多条输入时按时间顺序一起提供，并标明本轮输入的范围和发送者；最后一条消息处于这个范围内，角色可以针对整批输入回应。assistant 只表示观察角色自身的历史发言，其他角色发言与玩家发言都包含明确发送者身份。

## 11. 多角色与活动输入约束

| 信息或字段 | 用途与约束 |
|---|---|
| 角色实例、社群、消息发送者 | 明确本次观察者和实际交流对象；其他角色的私有信息不进入输入 |
| thought、utterance、reply_to_message_id | 发言结构与表达规则由第 2 节定义；回复目标必须是可见消息 |
| outcome=silent | 明确结束本次对话任务，不创建公开发言 |
| 关系 target | 每项变化指定真实目标；同一目标每维最多一次，判断及幅度使用第 8 节的三维规则 |
| 实例自身状态与有向关系 | 自身状态属于当前实例，关系按观察者和目标分别提供 |
| 活动棋局、私有观察、允许动作 | 由未来 ActivityTask 的专用输入和动作契约提供，具体边界见 [活动接入](activity-integration.md) |

标识使用本次真实输入中的值。NoOp 的许可按流程区分；视图以第一人称选择已有记录表达，核心支持引用包含实际记录类型、编号和版本。事实使用清楚的归属与来源性质，认知保留体验、理解或推断性质。日记遵守自己的来源与输出契约。

## 12. 正式记忆工具的文字与协议

工具名为 memory_search（记忆搜索）。工具定义的 description（说明文字）为：

在角色可见的长期记忆和相关对话中检索有限的记忆线索。

query 参数的 description 为：

想回想的主题、人物或事件

query 为非空字符串，上限 256 个字符；limit 为 1—5 的整数，默认 5。多角色扩展的社群、实例、会话上限和观察时间由任务授权提供，不加入模型可自由选择的参数。

工具返回 retrievalKind 和 results；结果保存 sourceKind、sourceId、sourceRef、contentVersion、retrievalPolicyVersion、summary，以及适用的 memoryId、memoryKind、occurredAtUtc。长期结果按真实记录类型保留事实或认知性质和必要时间，经过明确转换进入模型观察。执行外壳保存 tool、callId、ok、output，以及适用的 errorCode、progressed、newItemCount、noProgressStreak；权限来自任务，不由模型参数选择。检索与资格规则见 [记忆](memory.md#6-搜索与重建)。

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
| reflection_digest_coverage_mismatch | 请将 covers_through_sequence 设置为本次冻结材料的覆盖上限。 |
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

对话消息标注发送者、消息编号、提及对象及回复来源，当前角色自己的历史消息也保留这些信息。当前触发与根玩家输入通过明确编号区分，历史与输入按序号排列。指导允许回应另一名角色、自然附和、追问和合法沉默。程序排序、深度和剩余额度留在诊断，不进入角色表达要求。正式组装顺序见 [Agent 与模型](agents-and-models.md#2-提示与输出)，输出契约保持不变。

## 16. 反思提示组装

`reflection/common.md` → 节点所需人物正文 → 允许的状态、关系及旧记忆背景 → `materials/*.md` 与本批来源 → 可选 `reading_scope` 和已审核前驱 → `task.md` → `nodes/*.md`。材料和允许引用先由所属服务冻结，提示组装不导入存储模块。

共同资源定义信息性质和输出纪律，来源资源解释本批材料，节点正文负责选材、操作和视角。事实节点忠实保存信息，认知节点形成或更新认识，核心和关系节点选择已有内容表达。创作提示继续独立维护。

## 17. 长期整理与共同提示的完整正文

节点选择、事实审核和引用转换由运行层负责，正文定义各节点的写作与操作边界。具体字段遵循该节点输出契约。

### fact_extract

```text
整理角色在本批材料中实际获得、值得以后检索的信息。事实记录说明谁在什么时候表达或经历了什么，保留对象、条件和来源性质，不生成性格评价或新的因果解释。

本批原始消息提供谁说过什么。自述、转述、约定、计划和猜测保留原有性质；一句“我已经做完”首先是说话者的陈述，只有实际提供的正式结果才能证明业务动作完成。作者确认材料只保存当前角色确实可以知道的过去和信息。

段摘要帮助定位经历，旧事实帮助识别同一信息，人物正文帮助认清身份。它们不能替代本次新增事实的原始依据。thought 不证明其他人的行动、隐藏动机或客观属性。

每条记录围绕一项完整信息，用清楚的称呼和必要语境使它可以单独理解，不要求角色口吻或固定句式。普通寒暄、重复接话和没有后续价值的细节可以省略。未来承诺保留具体对象和事项，实际时间未知时保持未知，不能把整理时间当作发生时间。

本批与已提供旧事实表达同一信息时，选择那条旧事实并补充新的原始依据。不同时间的独立事件、不同条件的说法分别保存。发现旧模型提取与来源不一致时，可以提出纠正，填写实际旧记录引用及支持纠正的来源；不能删除或改写当时真正说过的话。

每项填写本节点 Schema 规定的操作、局部键或旧记录引用、内容主题、来源性质、正文、参与者、必要时间和 evidence_refs。正式参与者身份只从提供清单选择；背景人物保留材料里的称呼，不创建成员、实体、别名或关系边。

evidence_refs 只选真正支持本项的本批原始来源。旧记录引用使用输入提供的完整值，不自创存储编号、来源、版本或更新资格。模型置信度不能提高陈述或推测的证据等级。

返回前检查每条是否值得保留，是否增加了来源没有的动作、原因或判断，时间和条件是否完整。同一来源不因出现多份摘要成为多份独立证据。

有合法操作时返回 kind=memory_fact_extract、facts 和 evidence_refs。没有新的事实或依据时返回 kind=no_op 和简短 reason。只返回实际 JSON Schema 允许的一个 action 对象。
```

### cognition_reflect

```text
根据本批已经审核的事实候选、允许引用的旧事实、自身 thought 和已提供旧认识，判断角色是否形成了新的理解，或需要更新已有认识。

事实说明角色获得了什么信息，认知说明角色怎样理解。可以保存有限的印象、疑问、感受和对具体事项的判断；每条事实无需生成一条认识，换一种说法复述事实也不构成新的认识。

thought 已明确记录的当时感受，可以保留其时间和来源。现在根据经历推断的感受或判断不能补写成当时已经存在的内心。对方的说法、自己的理解和未知动机分别表达，不把自己的期待当作对方的承诺或态度。

先认清正在理解的人或事情。已有认识仍成立时保留；本批确有新依据时细化、减弱或修正，引用提供的旧认识及版本。一次经历不自动变成永久性格评价、所有人的共同属性或以后每次都要执行的相处规则。

人物背景影响角色看事情的角度，voice 帮助表达，二者不能补出新的外部事实。正文用角色自然的第一人称，可以直接说具体想法，不要求每条以“我觉得”开头，不用固定的防备、亲近或人生总结凑满字数。

支持事实使用本节点明确允许的完整引用；本批事实候选使用提供的局部引用，正式编号由运行编排层转换。自身主观来源填写自己的 evidence_refs。旧认识用于比较，不是新增的独立证据；不要反复从旧认识再生成更高一层认识。

每项按照实际 Schema 填写新增或更新操作、对象或事项、认识性质、正文、形成时间、适用范围、支持事实和自身原始依据。只能更新本次提供的旧记录，不能修改正式关系分数、短时状态、人设、别人的记忆或权威活动结果。

来源不足时保留不确定范围，不强行生成确定答案。没有值得保存的新认识时返回 kind=no_op 和简短 reason；有合法变化时返回 kind=memory_cognition_reflect、cognitions 和 evidence_refs。只返回实际 JSON Schema 允许的一个 action 对象。
```

### 共同反思正文

```text
完成当前节点规定的整理任务。原始消息、作者材料、自身内心、摘要、正式记录和旧认识保留各自的材料性质，不能因为进入本次输入就获得相同的事实资格。

事实提取忠实交代谁表达或经历了什么。认知记录说明角色怎样理解。段与连续摘要压缩经历以维持交流连续性；状态、关系和核心视图表达所属节点允许使用的材料。正文视角和写法遵守当前节点，不用共同规则强制所有事实写成第一人称。

名字、正式身份、时间、否定和条件按实际材料保存。未知保持未知，陈述保留说话者，判断保留理解者；人设和语气不能补写经历、动机或因果。文字按具体内容展开，删除重复评价和没有信息的总结，不要求统一长度或结论。

动作、字段、引用资格和输出上限以本节点的完整说明及实际 JSON Schema 为准。逐项依据各自保存，顶层合集不能替代它；旧背景与常驻视图不自动成为本次证据。

正式编号、版本、来源覆盖、状态修改和保存由运行编排层负责。缺少可靠内容时只在节点允许的情况下返回 no_op；需要推进摘要覆盖时返回其规定的摘要动作。

只返回当前节点允许的一个 JSON action，不附编辑过程、日志、额外解释或提交命令。
```

### 共同任务正文

```text
完成当前节点说明中的任务，只返回实际输出契约允许的一个 action JSON。

本节点允许引用的完整来源字符串：
$source_refs

来源字符串原样使用，不新增来源或修改版本。逐项依据按节点填写，顶层 evidence_refs 为实际逐项引用的去重合集。

旧记录、前驱事实候选和主体身份的引用资格由本节点提供的清单决定。局部引用不等于正式存储编号，程序负责转换及审核。

正文遵守当前节点的材料性质、视角、用途和预算。输出不包含 ReflectionBatch、ProposalEnvelope、操作命令或额外说明。
```
