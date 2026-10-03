# 本地管理接口

本文件描述已实现的管理查询、操作与导出。逐字段类型、枚举和可空字段以 [OpenAPI 契约](openapi.json) 为准；共同错误格式见 [HTTP 参考](http-api.md#5-错误内部接口和健康)。

## 1. 管理范围

全部路径位于 `/internal`。当前服务默认监听 `127.0.0.1`，管理接口供本地测试管理使用，没有管理员账户认证。社群和角色参数验证对象归属；账户访问控制需要按实际远程部署设计完成。普通玩家消息、轮次继续使用 `/api`，管理查询与导出的私人正文不能混入玩家缓存。

社群管理可以查看该社群全部消息，包括指定受众的消息。角色记忆、内心、冻结输入和反思要求明确社群与角色。消息详情返回实际受众的成员区间编号，避免只凭当前成员列表解释历史可见性。

诊断响应过滤已经清除的 Thought（私有内心记录）正文，保留来源编号和 `content_removed_at_utc`；数据库中的原始冻结输入继续用于恢复执行。显式开启的模型捕获文件独立保存，数据库清除不删除历史捕获文件。管理导出使用正式数据库记录。

## 2. 列表与分页

所有管理列表返回 `items`、`cursor`、`has_more`。`limit` 默认 50，允许 1—200。首次不传 `cursor`，后续原样返回；`has_more=false` 时 `cursor=null`。重新查看最新状态从第一页开始。管理分页用于浏览记录，玩家消息轮询继续使用其原有游标协议。

游标绑定查询种类、社群、角色、会话及筛选条件。更换范围或状态条件后重新读取第一页；无效或错用游标返回 400。按时间和编号稳定排序，消息按序号排序。不存在的范围返回 404，存在范围中的空列表返回 200。

列表返回概要。消息概要提供最多 160 个字符的 `text_preview`；冻结输入、生成产物、记忆正文通过详情读取。角色和会话列表复用已有公开对象列表 `/api/communities/{community_id}/characters` 与 `/api/communities/{community_id}/conversations`。

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
| GET K | 角色实例详情，含可用状态、原因与下次检查时间 |
| GET K/states | 当前有效状态、计算时间 `effective_at_utc`、分页状态历史 `history` |
| GET K/relationships | 分页有向关系：数值、态度、版本和资格证据 |
| GET K/relationships/{target_kind}/{target_id}/evidence | 分页实际关系证据；目标须属于社群 |
| GET V | 会话详情，含 `next_sequence` |
| GET V/members | 分页完整成员历史区间 |
| GET V/messages | 分页消息概要 |
| GET V/messages/{message_id} | 完整消息、来源结果、追踪编号及实际受众 |
| GET V/turns | 分页轮次概要 |
| GET V/turns/{turn_id} | 轮次受众、完成结果、参与决定、任务编号与精确输入消息编号 |
| GET C/tasks | 分页对话任务；可按 `conversation_id`、`character_id`、`status` 筛选 |
| GET /internal/characters/{character_id}/tasks/{task_id} | 必填 `community_id`；任务概要、冻结上下文及各次审核结果 |
| GET /internal/characters/{character_id}/tasks/{task_id}/context | 必填 `community_id`；实际冻结上下文的管理投影 |
| GET /internal/traces/{correlation_id} | 必填 `community_id`；可选 `character_id`；真实追踪及投递状态 |

任务的 `completed`（完成）状态可以对应发言或合法沉默。生成结果中的 `no_proposal` 表示模型没有提出发言；轮次参与决定中的 `outcome=silent` 表示沉默。重试和模型失败仍保留真实错误与次数。

追踪从权威业务对象验证归属。任务和反思使用对应 `trace_id`；玩家消息可使用 `message_id` 或回执 `trace_id`，查询服务解析为实际消息关联编号。消息回执 `trace_id` 是事件编号，任务 `trace_id` 是关联编号。指定角色时只接受属于该角色的任务、反思或角色消息，玩家消息追踪通过社群管理范围读取。非法归属和不存在的关联返回 404。

## 4. 记忆和反思查询

| 方法与路径 | 查询或响应 |
|---|---|
| GET K/memory/{collection} | 分页记忆概要；`collection` 是 segments、digests、entries、entities 或 edges |
| GET K/memory/{collection}/{record_id} | 对应类别的详情，响应通过 `record_kind` 区分 |
| GET K/reflection/runs | 分页反思图概要；可按 `status` 筛选 |
| GET /internal/reflection/runs/{graph_run_id} | 必填 `community_id`、`character_id`；图、节点、冻结材料、产物、审核、事实及追踪 |
| GET /internal/reflection/runs/{graph_run_id}/nodes/{node_task_id}/input | 必填相同范围；节点输入是否已经具备及实际输入 |

记忆类别：`segments` 为材料段及段摘要，`digests` 为连续摘要，`entries` 为长期页，`entities` 为实体与别名，`edges` 为实体关系。segments、digests 支持可选 `conversation_id` 筛选；其他类别没有会话字段，传入该筛选返回 400。

段详情包含精确来源、摘要覆盖和长期整理消费记录。摘要和长期页详情包含冻结批次、前驱摘要编号、来源段与版本。实体详情包含实际别名和长期页关联，实体关系保留已有来源字段；没有来源长期页的关系保持 `source_memory_id=null`。

节点输入来自原图快照及已经绑定的前驱产物。依赖未完成或节点未激活时 `input_ready=false`、`input=null`，页面不能把尚未形成的输入当成已执行材料。已具备输入时使用与正式执行相同的构造方法，再过滤已清除正文。

## 5. 有限管理操作

所有请求正文拒绝未知字段。操作复用正式服务，模型调用由后台执行，数据库写事务中不请求模型。

| 方法与路径 | 请求正文 | 成功响应 |
|---|---|---|
| POST K/conversations/{conversation_id}/segments | `first_sequence`、`through_sequence` | 200，`outcome` 与实际段详情 |
| POST K/reflection/segments | `segment_id` | 202，安排或复用的图概要、来源类型和编号 |
| POST K/reflection/summaries | `conversation_id`、`consumer`、`through_sequence`；`limit` 默认16，1—200 | 202，同样的调度结果；没有材料时返回空图 |
| POST /internal/reflection/runs/{graph_run_id}/restart | 无正文；查询必填 `community_id`、`character_id` | 202，原图重新启动结果 |

封段的起止序号必须为正整数，起点不超过终点，终点不超过已有消息。起点指定下一条角色可见且尚未归段的消息。服务受实际材料预算约束，返回的终点可能小于请求终点；下一次从实际下一条未归段消息开始。相同起点重复请求返回已有段，不重复生成后续段。请求终点小于已有段终点，或起点与下一条未归段材料不同，返回 409。没有未归段材料时 `outcome=no_material`、`segment=null`。

摘要 `consumer` 只允许 `continuity_compress`（连续性压缩）与 `memory_organize`（长期记忆整理）。材料冻结、前驱选择和消费限制由正式服务执行。没有可用摘要时 `outcome=no_material`；运行中返回 `scheduled`，已形成终态的同来源图返回 `existing`。202 表示完成安排，执行情况通过图查询读取。

失败图重新启动只支持 `failed` 且没有最终审核结果的图；原始来源须仍然有效。它保留原图编号、冻结输入和成功产物，重新安排失败节点及受必需节点失败影响的节点。其他状态返回 409；重复重新启动已经恢复的图也返回 409。部分成功补做、日记和认识刷新尚未提供管理操作。

## 6. 范围化材料导出

POST `V/export` 请求：

```json
{"first_sequence":1,"through_sequence":30,"character_id":"jin-a"}
```

起止序号必填，范围须位于已有消息内，每次最多包含 10000 个序号。`character_id` 可选。成功返回 200、JSON 正文及下载文件名 `echo-commons-materials.json`，服务器不创建导出文件。

导出含 `schema_version=1`、实际 `scope`、导出时间、各类数量和材料。一次读取使用同一数据库读事务，后台继续执行不会使本次导出混合前后两个状态。

- 社群会话范围导出全部所选消息、实际受众、相关轮次、任务概要和成员区间；角色内心、生成结果正文和记忆为空。
- 指定角色后，消息采用该角色的真实成员区间与受众规则过滤；只包含对应角色的任务、范围内发言的审核结果和内心记录。
- 材料段完整位于范围内时导出段详情；摘要的全部来源段与前驱摘要均在范围内时导出正文；长期页的来源批次完整位于范围内时导出正文。
- 跨范围回复、轮次输入、部分覆盖的段、前驱摘要、冻结上下文和实体关联，通过 `references` 保存来源编号与归属，正文不自动扩大。

模型密钥、完整模型捕获、其他社群数据、其他角色私人正文不进入导出。模板预加载记忆没有对应本次会话材料来源，也不进入此类导出。导出是可追溯的测试材料集合；完整数据库备份继续使用既有 CLI（命令行工具）。

## 7. 管理页面接入顺序

先发现社群与成员，复用角色和会话列表；选择会话后读取消息概要、轮次和任务。选择任务读取冻结输入与审核结果，通过返回的追踪编号定位过程。选择角色后查询材料段、反思和长期页，操作结果保留实际段或图编号。

每次切换社群、会话、角色或筛选条件清除对应游标和私人正文缓存。管理错误使用共同的 400、404、409、422、500、503 契约；页面保留请求范围，以便定位输入或归属错误。
