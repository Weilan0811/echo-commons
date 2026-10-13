# 本地管理接口

本文件描述已实现的管理查询、操作与导出。逐字段类型、枚举和可空字段以 [OpenAPI 契约](openapi.json) 为准；共同错误格式见 [HTTP 参考](http-api.md#5-错误内部接口和健康)。

记忆索引检查使用 `GET /internal/characters/{character_id}/memory-index?community_id=...`，返回文档数、向量数、向量配置和最近失败原因。`POST /internal/characters/{character_id}/memory-index/rebuild?community_id=...` 重建该实例的全文投影，清除对应向量与失败记录；向量开启时由后台补建。正文、消息和摘要保持保存。

两个索引接口均返回 `MemoryIndexStatus`；失败项 `MemoryIndexFailure` 提供材料类型、编号、错误类型、提供方尝试次数与记录时间。管理玩家页面通过 `GET /internal/players/{player_id}/image-generations` 和 `GET /internal/players/{player_id}/character-candidates` 分页查看图片与人物创作任务，管理响应保留 `error_code`，公开响应省略该字段。图片诊断还提供外部任务编号及期限。

## 1. 管理范围

全部路径位于 `/internal`。当前服务默认监听 `127.0.0.1`，管理接口供本地测试管理使用，没有管理员账户认证。社群和角色参数验证对象归属；账户访问控制需要按实际远程部署设计完成。普通玩家消息、轮次继续使用 `/api`，管理查询与导出的私人正文不能混入玩家缓存。

社群管理可以查看该社群全部消息，包括历史保存的私有消息与旧轮次恢复产生的回应。角色记忆、内心、冻结输入和反思要求明确社群与角色。消息详情返回实际受众的成员区间编号，避免只凭当前成员列表解释历史可见性。

诊断响应过滤已经清除的 Thought（私有内心记录）正文，保留来源编号和 `content_removed_at_utc`；数据库中的原始冻结输入继续用于恢复执行。显式开启的模型捕获文件独立保存，数据库清除不删除历史捕获文件。管理导出使用正式数据库记录。

### 1.1 访问边界

管理接口不做管理员账户认证，默认随服务监听 127.0.0.1，因此只在本机可达。管理查询可以读取角色内心、冻结输入与记忆正文，这些内容玩家端不可见；本节列出的写端点在无鉴权状态下具备完整能力，因此本文件的适用边界是本机调试。

部署到本机以外的环境前必须自行增加访问控制。本项目不提供令牌、账户或权限模型，原因是管理面只面向部署者本人：开源部署中每个实例只有部署者可以访问，不存在需要区分的管理角色。需要远程访问的部署者应在反向代理或网络层限制 `/internal` 前缀的来源。

绑定到非回环地址前请确认这一点。写端点包括成员加入与移除、封段、安排反思与重启图，其中重启图会触发模型调用。

前端对应处理：管理页面不保存凭据，不做权限控制，也不隐藏端点。界面按调试工具的密度呈现，错误原样展示。

### 1.2 测试数据清理

`POST /internal/maintenance/cleanup` 按明确编号清理测试数据。请求允许 `community_ids`、`draft_ids`、`player_ids`、`asset_ids`、`generation_ids` 五组数组，至少指定一个编号。重复编号只处理一次；不存在的编号登记在 `missing`，不会扩大删除范围。`dry_run` 默认 `true`，只预览；明确设为 `false` 才执行删除。

```json
{
  "community_ids": ["test-community"],
  "draft_ids": [],
  "player_ids": [],
  "dry_run": true
}
```

先通过社群状态接口暂停目标社群，再预览清理范围。预览返回 `counts`（按实际数据库表统计的记录数量）、`missing`（未找到的编号）、`blockers`（阻止清理的对象编号、种类及原因）和 `retained_resources`（保留的外部资源）。预览始终返回 200；执行时重新检查范围，有阻止对象返回 409、`error.code=cleanup_blocked`，并保留相同的详细字段。成功执行返回 200、`deleted=true`；`counts` 表示本次删除前确定的数量。重复执行已删除的范围返回零数量和缺失编号。

社群清理包含成员、角色实例、会话、消息、群聊轮次、任务、执行记录、记忆、全文与向量索引、阅读位置、关联追踪和实时事件。草稿及玩家需要单独选择。指定草稿的候选和固定人物资源一起删除；范围外角色仍使用该人物资源时拒绝。玩家仍属于范围外社群，拥有未选择的草稿或人物资源，或保留范围外会话阅读记录时拒绝。

执行中的回复、记忆反思、人物创作、向量索引和追踪投递会阻止相关范围清理。暂停后仍未结束的任务调用继续计入检查。删除在一个事务中完成，数据库失败全部回滚；外键检查始终启用。删除成功后唤醒原社群 SSE 订阅，发送 `access_revoked` 并关闭连接。

数据库结构、全局事件序号、前端预设、日志、备份和诊断捕获文件保留。资产和生成任务需要明确指定。业务引用随所选社群或草稿解除；范围外业务、裁剪头像来源引用和生成中的任务会阻止资产删除。玩家仍有未选资产或任务时拒绝清理。资产先进入删除状态，数据库提交后移除文件；中断后启动维护继续处理。生成任务完成后的资产保持独立，删除任务不会自动删除资产。接口没有全库重置、名称匹配或客户端 SQL 参数。

## 2. 列表与分页

所有管理列表返回 `items`、`cursor`、`has_more`。`limit` 默认 50，允许 1—200。首次不传 `cursor`，后续原样返回；`has_more=false` 时 `cursor=null`。重新查看最新状态从第一页开始。管理分页用于浏览记录，玩家消息轮询继续使用其原有游标协议。

游标绑定查询种类、社群、角色、会话及筛选条件。更换范围或状态条件后重新读取第一页；无效或错用游标返回 400。按时间和编号稳定排序，消息按序号排序。不存在的范围返回 404，存在范围中的空列表返回 200。

列表返回概要。消息概要提供最多 160 个字符的 `text_preview`；冻结输入、生成产物、记忆正文通过详情读取。角色和会话使用管理侧独立完整分页列表，玩家侧按读取身份筛选。

下表使用三个前缀：

- `C`：`/internal/communities/{community_id}`。
- `K`：`C/characters/{character_id}`。
- `V`：`C/conversations/{conversation_id}`。

## 3. 对象和互动查询

| 方法与路径 | 查询或响应 |
|---|---|
| GET /internal/communities | 分页社群列表 |
| GET C | 社群详情 |
| GET /internal/players | 分页玩家列表 |
| GET /internal/players/{player_id} | 玩家详情 |
| GET C/members | 分页社群成员，包含身份和加入时间 |
| GET C/characters | 分页完整角色实例，含公共名字与头像 |
| GET C/conversations | 分页社群全部会话，可按 kind、status 筛选 |
| GET K | 角色实例详情，含可用状态、原因与下次检查时间 |
| GET K/states | 当前有效状态、计算时间 `effective_at_utc`、分页状态历史 `history` |
| GET K/relationships | 分页有向关系：自然称呼、数值、态度、版本、资格证据与最近刷新进度 |
| GET K/relationships/{target_kind}/{target_id}/evidence | 分页实际关系证据；目标须属于社群 |
| GET V | 会话详情，含 `next_sequence` |
| GET V/members | 分页完整成员历史区间 |
| GET V/messages | 分页消息概要 |
| GET V/messages/{message_id} | 完整消息、来源结果、追踪编号及实际受众 |
| GET V/turns | 分页轮次概要 |
| GET V/turns/{turn_id} | 轮次受众、完成结果、参与决定、任务及来源编号；chain 固定额度与计数、candidates 候选进度、triggers 触发状态 |
| GET C/tasks | 分页对话任务；可按 `conversation_id`、`character_id`、`status` 筛选 |
| GET /internal/characters/{character_id}/tasks/{task_id} | 必填 `community_id`；任务概要、冻结上下文、各次审核结果及分页 `recovery_history` |
| GET /internal/characters/{character_id}/tasks/{task_id}/context | 必填 `community_id`；实际冻结上下文的管理投影 |
| GET /internal/traces/{correlation_id} | 必填 `community_id`；可选 `character_id`；真实追踪及投递状态 |

任务的 `completed`（完成）状态可以对应发言或合法沉默。生成结果中的 `no_proposal` 表示模型没有提出发言；轮次参与决定中的 `outcome=silent` 表示沉默。重试和模型失败仍保留真实错误与次数。

`ConversationResultView.payload` 按 `status` 区分两种生成结果，OpenAPI 用 `oneOf`（联合类型）和 `discriminator`（区分字段）声明：`completed` 包含 `output.contract` 与 `output.payload`，后者包含 `utterance`（发言）、可空 `thought`（内心正文）与可空 `reply_to_message_id`（回复来源）；`no_proposal` 的 `output=null`。模型返回的 `{"outcome":"silent"}` 转换为 `no_proposal`，通过审核后参与决定为 `silent`。失败和重试使用任务及恢复历史表达，不增加无产出变体。

生成结果的 `completed` 只表示生成完成，是否形成正式消息看外层审核 `status`（approved／rejected／expired）。管理查询从独立 Thought 记录读取已审核保存的内心正文；没有记录或已清除时 `thought=null`，清除时间见 `thought_removed_at_utc`。发言产物存储不重复保存内心正文，玩家消息接口继续不返回内心。

追踪从权威业务对象验证归属。任务和反思使用对应 `trace_id`；玩家消息可使用 `message_id` 或回执 `trace_id`，查询服务解析为实际消息关联编号。消息回执 `trace_id` 是事件编号，任务 `trace_id` 是关联编号。指定角色时只接受属于该角色的任务、反思或角色消息，玩家消息追踪通过社群管理范围读取。非法归属和不存在的关联返回 404。

## 4. 记忆和反思查询

| 方法与路径 | 查询或响应 |
|---|---|
| GET K/memory/{collection} | 分页记忆概要；`collection` 是 segments、digests、facts 或 cognitions |
| GET K/memory/{collection}/{record_id} | 对应类别的详情，响应通过 `record_kind` 区分 |
| GET K/reflection/runs | 分页反思图概要；可按 `status` 筛选 |
| GET K/reflection/core-memory | 当前核心记忆、上限、依据与最近刷新进度 |
| GET /internal/reflection/runs/{graph_run_id} | 必填 `community_id`、`character_id`；图、节点、冻结材料（含作者材料与正式事实）、产物、审核、事实、补充运行及追踪 |
| GET /internal/reflection/runs/{graph_run_id}/nodes/{node_task_id}/input | 必填相同范围；节点输入是否已经具备及实际输入 |

记忆类别：`segments` 为材料段及段摘要，`digests` 为连续摘要，`facts` 为事实记录，`cognitions` 为角色认知。segments、digests 支持可选 `conversation_id` 筛选；其他类别没有会话字段，传入该筛选返回 400。

本参考记录实际运行接口。长期事实和认知的业务设计见 [记忆](../design/memory.md)，验证范围见 [状态](../status.md)；集合和字段以 [OpenAPI](openapi.json) 为准。

段详情包含精确来源、摘要覆盖和长期整理消费记录；连续摘要提供冻结批次、前驱及来源段。事实和认知详情通过 `record_kind` 分派，提供性质、时间、状态、逐项 `sources`、`versions` 历史和 `stages` 阶段结果。原文按实际身份和版本读取，缺失时明确显示不可读；批次范围不能替代逐项依据。核心响应提供类型明确的 `supporting_records`。

节点输入来自原图快照及已经绑定的前驱产物。依赖未完成或节点未激活时 `input_ready=false`、`input=null`，页面不能把尚未形成的输入当成已执行材料。已具备输入时使用与正式执行相同的构造方法，再过滤已清除正文。

## 5. 有限管理操作

所有请求正文拒绝未知字段。操作复用正式服务，模型调用由后台执行，数据库写事务中不请求模型。

PUT、DELETE `V/members/{actor_kind}/{actor_id}` 分别加入和移除同社群指定主体。加入正文、退出查询必填 `expected_membership_version` 和 `client_operation_id`，返回 200、实际 membership、操作完成时 membership_version 与成员状态。同编号同内容返回原结果，不同内容返回 idempotency_conflict；旧版本返回 membership_version_conflict。直接会话只恢复原始固定身份。规则见 [玩家与成员设计](../design/player-api.md)。

| 方法与路径 | 请求正文 | 成功响应 |
|---|---|---|
| POST K/conversations/{conversation_id}/segments | `first_sequence`、`through_sequence` | 200，`outcome` 与实际段详情 |
| POST K/reflection/segments | `segment_id` | 202，安排或复用的图概要、来源类型和编号 |
| POST K/reflection/core-memory | UUID `request_id` | 202，正式核心记忆刷新；重复请求返回同一运行 |
| POST K/reflection/summaries | `conversation_id`、`consumer`、`through_sequence`；`limit` 默认16，1—200 | 202，同样的调度结果；没有材料时返回空图 |
| POST /internal/reflection/runs/{graph_run_id}/restart | 无正文；查询必填 `community_id`、`character_id` | 202，原图重新启动结果 |

封段的起止序号必须为正整数，起点不超过终点，终点不超过已有消息。起点指定下一条角色可见且尚未归段的消息。服务受实际材料预算约束，返回的终点可能小于请求终点；下一次从实际下一条未归段消息开始。相同起点重复请求返回已有段，不重复生成后续段。请求终点小于已有段终点，或起点与下一条未归段材料不同，返回 409。没有未归段材料时 `outcome=no_material`、`segment=null`。

摘要 `consumer` 只允许 `continuity_compress`（连续性压缩）与 `memory_organize`（长期记忆整理）。材料冻结、前驱选择和消费限制由正式服务执行。没有可用摘要时 `outcome=no_material`；运行中返回 `scheduled`，已形成终态的同来源图返回 `existing`。202 表示完成安排，执行情况通过图查询读取。

`failed` 且没有最终审核结果的图重新启动时，保留原图编号、冻结输入和成功产物，安排失败节点及受必需节点失败影响的节点。段反思和认识刷新的 `partial` 图创建补充运行，只执行失败分支，不重复提交成功事实；重复请求返回已有补充运行。原始来源须仍然有效，其他状态返回 409。图详情的 `supplement` 提供原运行和重试分支，`supplement_run_ids` 列出补充运行编号。认识刷新跟随正式事实自动安排，日记没有运行入口。

重新启动会恢复本轮重试额度，累计次数保留在节点的 `attempt_count`，本轮起点保存在 `attempt_base_count`。供应商暂时故障的等待及总次数见 [恢复规则](../design/errors-and-recovery.md#3-三层次数与期限)。恢复历史的 `failure` 包含可用的 `status_code`、`exception_type`、`request_id`，下一次执行时间保存在恢复记录中；旧记录没有诊断信息时为空。

## 6. 范围化材料导出

POST `V/export` 请求：

```json
{"first_sequence":1,"through_sequence":30,"character_id":"jin-a"}
```

起止序号必填，范围须位于已有消息内，每次最多包含 10000 个序号。`character_id` 可选。成功返回 200、JSON 正文及下载文件名 `echo-commons-materials.json`，服务器不创建导出文件。

导出含 `schema_version=1`、实际 `scope`、导出时间、各类数量和材料。一次读取使用同一数据库读事务，后台继续执行不会使本次导出混合前后两个状态。

- 社群会话范围导出全部所选消息、实际受众、相关轮次、任务概要和成员区间；角色内心、生成结果正文和记忆为空。
- 指定角色后，消息采用该角色的真实成员区间与受众规则过滤；只包含对应角色的任务、范围内发言的审核结果和内心记录。
- 材料段完整位于范围内时导出段详情；摘要的全部来源段与前驱摘要均在范围内时导出正文；事实和认知的来源批次完整位于范围内时导出对应版本及逐项依据。
- 跨范围回复、轮次输入、部分覆盖的段、前驱摘要、冻结上下文和页面来源，通过 `references` 保存来源编号与归属，正文不自动扩大。

模型密钥、完整模型捕获、其他社群数据、其他角色私人正文不进入导出。模板预加载记忆没有对应本次会话材料来源，也不进入此类导出。导出是可追溯的测试材料集合；完整数据库备份继续使用既有 CLI（命令行工具）。

## 7. 管理页面接入顺序

先发现社群与成员，再读取管理角色和会话列表；选择会话后读取消息概要、轮次和任务。选择任务读取冻结输入与审核结果，通过返回的追踪编号定位过程。选择角色后查询材料段、反思、事实和认知，操作结果保留实际段或图编号。

每次切换社群、会话、角色或筛选条件清除对应游标和私人正文缓存。管理错误使用共同的 400、404、409、422、500、503 契约；页面保留请求范围，以便定位输入或归属错误。

## 7. 错误与恢复诊断

对话任务和反思图列表增加 `last_failure`（最近完整失败）、`last_recovery_action`（最近实际动作）、`next_attempt_at_utc`（下次尝试时间）和 `retry_exhausted`（次数耗尽）。旧记录没有正式诊断时这些字段可为空；保留已有状态和错误码。下一次时间只适用于当前等待状态。

对话任务详情和反思节点输入详情增加 `recovery_history`。这部分独立使用 `limit` 默认 50、上限 200 和 `cursor`，返回既有 `Page` 结构。游标绑定社群、角色、任务及图。图详情增加 `recovery_summary` 和按节点编号组织的 `node_recovery`，避免重复返回所有节点完整历史。

每项事件包含事件编号与种类、任务编号与种类、尝试、租约代次、社群与角色、调用与追踪、记录时间和安全 `payload`。反思包含 `graph_run_id` 和 `graph_execution_generation`，人工重启前后的记录可明确区分。

载荷中的 `recovery` 分别提供原始决定、实际动作、目标状态、有效等待、下次时间和耗尽。`observation` 提供真实请求与供应商次数及当前执行内修正；缺失值表示没有完整观察。`repair_hint_used` 是调用开始实际使用的提示，恢复决定中的提示用于计划下次调用。生命周期事件不会冒充调用或覆盖执行恢复决定。

`/internal/traces/{correlation_id}` 同时提供 `execution.*` 安全追踪及独立投递状态。普通日志排除提示正文、完整模型输入输出、内心和密钥。运行规则见 [错误与恢复设计](../design/errors-and-recovery.md)。

## 关系描述刷新

`POST /internal/communities/{community_id}/characters/{character_id}/reflection/relationship-attitudes`，要求完整记忆模式，成功返回 202。请求包含 UUID `request_id`，可选 `target` 使用 `kind` 与 `actor_id`；省略时分别处理全部已初始化目标。返回数组，每项包含目标、`graph_run_id`、`source_version` 和 `error_code`。证据缺失时运行编号为空并返回 `relationship_evidence_missing`；不调用模型。没有可刷新的已初始化关系返回 409。

同一请求编号和范围复用原运行；同编号改变社群、角色或目标范围返回 409。手动刷新采用独立批次，重新读取当前事实，保留旧批次、冻结输入和结果。描述保存不修改关系数值。失败恢复复用已有图重试及补充图入口。

关系分页查询增加 `target_name` 和 `attitude_refresh`。后者为空或包含最近 `graph_run_id`、`status`、`source_version`、`request_kind` 和 `error_code`。这些字段仅供管理端使用，行为及证据规则见 [认识刷新设计](../design/reflection/view-refresh.md#4-关系描述与目标进度)，精确结构见 [OpenAPI](openapi.json)。
