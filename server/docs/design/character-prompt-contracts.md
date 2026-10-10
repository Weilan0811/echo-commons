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

`render_persona` 使用任务绑定的 agent-contract、profile、relational-dynamics 和可选 voice 正文。聊天与核心记忆节点使用全部四类资源；其他反思节点使用前三类。身份正文不复制到任务提示资源中。

## 5. 共同反思输出规则

完整正文见 [reflection/common.md](../../src/echo_commons/resources/prompts/reflection/common.md)。共同规则保留事实、说法、判断、猜测和计划的性质，以明确人物和事项组织正文，不把一次表现概括为日后的行为要求。经历与主观认识使用第一人称；名称、三元组和枚举按节点契约填写。背景资料和前驱产物不能替代本节点允许引用的来源。内容范围、长度和结构由节点决定。

## 6. 节点职责与资源

每个模型节点的职责、判断要求及输出示例放在同一份资源中，由 ReflectionNodeDefinition（固定节点定义）指定路径。规划与聚合节点由程序执行，不读取模型提示。

| 节点 | 完整提示资源 |
|---|---|
| segment_summary_plan | [段摘要与后续分析选择](../../src/echo_commons/resources/prompts/reflection/nodes/segment_summary_plan.md) |
| relationship_reflect | [关系变化判断](../../src/echo_commons/resources/prompts/reflection/nodes/relationship_reflect.md) |
| state_reflect | [状态变化判断](../../src/echo_commons/resources/prompts/reflection/nodes/state_reflect.md) |
| continuity_compress | [连续性压缩](../../src/echo_commons/resources/prompts/reflection/nodes/continuity_compress.md) |
| page_compose | [长期记忆页整理](../../src/echo_commons/resources/prompts/reflection/nodes/page_compose.md) |
| graph_extract | [实体与关系提取](../../src/echo_commons/resources/prompts/reflection/nodes/graph_extract.md) |
| core_memory_view | [核心记忆认识](../../src/echo_commons/resources/prompts/reflection/nodes/core_memory_view.md) |
| state_summary_view | [状态概括](../../src/echo_commons/resources/prompts/reflection/nodes/state_summary_view.md) |
| relationship_attitude_view | [关系态度](../../src/echo_commons/resources/prompts/reflection/nodes/relationship_attitude_view.md) |

## 7. 节点共同任务说明

[reflection/task.md](../../src/echo_commons/resources/prompts/reflection/task.md) 声明证据引用及程序负责的字段。代码填入实际允许来源；连续性节点还填入本批结束消息序号。变量使用标准库 `string.Template` 替换，材料正文不作为模板解释。

## 8. 六类节点的完整任务细则

段摘要、关系、状态、连续性、长期页和实体提取的完整要求见第 6 节对应资源。三个认识刷新节点也各有独立完整提示。

关系变化与关系态度共同读取 [三维关系含义](../../src/echo_commons/resources/prompts/common/relationship-dimensions.md)。关系变化判断本次方向与幅度；关系态度理解已经保存的关系数值与历史证据，不修改分数。

## 9. 材料情境与来源解释

| 来源情境 | 提示资源与含义 |
|---|---|
| 对话段、摘要批次 | [dialogue.md](../../src/echo_commons/resources/prompts/reflection/materials/dialogue.md)：说明真实对话材料，区分发言、内心与摘要 |
| 作者材料批次 | [author.md](../../src/echo_commons/resources/prompts/reflection/materials/author.md)：区分过去经历、习惯、设定和采访观点 |
| 正式事实变化批次 | [facts.md](../../src/echo_commons/resources/prompts/reflection/materials/facts.md)：依据已保存事实更新认识，不重新修改事实 |

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

核心记忆以 `核心记忆` 为标题，下一行加入正文；聊天共同指导说明状态、关系和记忆的使用方式。核心刷新通过 `reading_scope` 提供本次页数、未读页数、完整性、来源可读状态和旧正文，范围信息不作为事实引用。版本和已处理页面记录保存在运行层。自身状态摘要以 `当前状态摘要` 为标题，下一行加入正文；每份段摘要以 `近期消息段摘要` 为标题，下一行加入正文。同一段落包含多份内容时，以两个换行分隔。

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
| stranger | 你和对方目前还是陌生人。 |
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

标识使用本次真实输入中的值。NoOp 的许可按图区分；视图采用共同反思的第一人称与来源规则，按已提交事实分别使用关系态度、状态概括和核心记忆提示；核心记忆引用使用输入中的原始记忆编号。日记专属提示与运行仍暂缓。

## 12. 正式记忆工具的文字与协议

工具名为 memory_search（记忆搜索）。工具定义的 description（说明文字）为：

在角色可见的长期记忆和相关对话中检索有限的记忆线索。

query 参数的 description 为：

想回想的主题、人物或事件

query 为非空字符串，上限 256 个字符；limit 为 1—5 的整数，默认 5。多角色扩展的社群、实例、会话上限和观察时间由任务授权提供，不加入模型可自由选择的参数。

工具返回 retrievalKind 和 results；每项包括 sourceKind、contentVersion、retrievalPolicyVersion、sourceId、sourceRef、summary，以及适用时的 memoryId、memoryKind、occurredAtUtc。工具观察外壳保存 tool、callId、ok、output、适用时的 errorCode、progressed、newItemCount、noProgressStreak。新内部对象可以保持独立类型，通过明确转换生成上述模型可见字段。

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
| reflection_evidence_unknown | 请仅引用本次输入允许的 evidence_refs。 |
| reflection_relationship_target_unknown | 请仅选择本次输入允许的关系目标。 |
| reflection_digest_coverage_mismatch | 请将 covers_through_sequence 设置为本次冻结材料的覆盖上限。 |
| reflection_entity_duplicate | 请为本次输出中的每个实体使用唯一的 entity_id。 |
| reflection_edge_target_unknown | 请让每条关系边的 from_entity_id 和 to_entity_id 引用本次输出中已有的实体。 |
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

## 14. 群聊来源与连续接话

对话消息标注发送者、消息编号、提及对象及回复来源，当前角色自己的历史消息也保留这些信息。当前触发与根玩家输入通过明确编号区分，历史与输入按序号排列。指导允许回应另一名角色、自然附和、追问和合法沉默。程序排序、深度和剩余额度留在诊断，不进入角色表达要求。正式组装顺序见 [Agent 与模型](agents-and-models.md#2-提示与输出)，输出契约保持不变。

## 反思提示的实际组装

`reflection/common.md` → 人物正文 → 当前状态、关系和记忆背景 → `materials/*.md` 与本次来源 → 可选 `reading_scope` 与前驱产物 → `task.md` → `nodes/*.md`。`reading_scope` 由节点投影显式传入，只有需要它的核心分支读取；模型输入包含页数、完整性和旧正文，不包含用于保存进度的候选版本表。提示组装不导入存储模块。共同资源负责写作和事实性质，来源资源解释证据含义，节点资源负责业务选材与字段。创作提示继续独立维护。
