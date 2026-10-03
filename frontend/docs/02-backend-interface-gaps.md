# 后端接口缺口清单

状态：规划，尚未实现。
更新日期：2026-10-03。
提交方：前端。
接收方：后端。
对接基线：后端 `feat/backend` 分支提交 `7cb5afa`（本地管理接口）。

本文列出前端仍需依赖、但当前契约未提供的接口。每项按 [推进计划](../../docs/01-project-roadmap.md) 的要求说明操作范围、路径、请求、响应、可见范围与完成语义。

**本文不是已实现能力的清单。** 已实现能力见 [HTTP 参考](../../server/docs/reference/http-api.md)，以及后端分支新增的 `server/docs/reference/management-api.md`（本地管理接口，合并 `feat/backend` 后位于上述目录）。本文任何条目都不应写入那两份文档。

## 1. 背景：缺口已从 `/api` 转到 `/internal`

后端在 `feat/backend` 上补齐了管理侧能力，路径全部位于 `/internal`，共 30 条，覆盖社群、玩家、成员、会话、消息、轮次、任务、记忆、反思、追踪、材料封段、摘要安排、失败图重启与范围化导出。

**公开 `/api` 接口没有变化**，仍是 13 条。因此前端的处境与上一版文档不同：

| 上一版假设 | 实际实现 |
|---|---|
| 需要新增 `/api/communities` 列出玩家参与的社群 | `/internal/communities` 提供分页社群列表，再用 `/internal/communities/{community_id}/members` 读成员判断归属 |
| 需要新增玩家维度会话列表 | 未实现，仍需从社群全量会话列表筛选 |
| 需要给 `ConversationView` 补参与者 | 未补字段，改为读 `/internal/communities/{community_id}/conversations/{conversation_id}/members` |
| 需要新增管理接口 | 已实现，见本地管理接口文档 |

因此本文不再是"催后端补接口"的清单，而是**记录前端如何适配已实现的接口，以及哪些需求仍未满足**。

### 一处需要后端留意的边界

管理接口文档说明其为本地测试管理用途，没有管理员账户认证，并要求管理数据缓存与玩家消息读取身份分别维护。

但会话参与者只能通过 `/internal` 取得，玩家端会话列表因此依赖管理路径。前端按最小范围使用（只读成员身份，不读消息正文、记忆或诊断），但这确实让玩家界面触及了管理范围。若后续认为玩家端不应依赖 `/internal`，需要后端提供一个 `/api` 侧的会话成员读取入口；在此之前前端按现状适配，不额外要求改动。

## 2. 剩余缺口与优先级

| 优先级 | 需求 | 影响 |
|---|---|---|
| P1 | 玩家维度的会话列表 | 会话列表需加载社群全量会话后按成员筛选，前端需额外请求每个会话的成员区间 |
| P1 | `/api` 侧的会话成员读取 | 玩家端目前依赖 `/internal`，边界不清晰 |
| P2 | 未读与最后消息摘要 | 多用户下没有通知入口，测试效率下降 |
| P2 | `401` / `403` 错误语义 | 没有凭据场景，无法表达身份问题 |
| P2 | 角色形象字段 | 前端已按有图用图、没图回退实现，字段可让数据结构先就位 |
| P3 | 写入的乐观并发复核 | 多用户同时操作时前端无法区分冲突与失败 |
| P3 | 活动对象读取 | 阶段五接入前需要 |

## 3. 已实现接口与前端适配

以下是原先列为缺口、现已由后端补齐的能力，以及前端采用的实际调用方式。前端适配后端既有接口，不要求后端改动。

### 3.1 社群与玩家发现

| 需求 | 实际接口 | 返回 |
|---|---|---|
| 列出社群 | `GET /internal/communities` | `Page_CommunityView_`：`items`、`cursor`、`has_more` |
| 读取社群成员 | `GET /internal/communities/{community_id}/members` | `Page_CommunityMemberView_`：成员含 `actor_kind`、`actor_id`、`joined_at_utc` |
| 列出玩家 | `GET /internal/players` | `Page_PlayerView_` |

**社区列表不按玩家过滤**，接口只有 `cursor` 与 `limit` 两个查询参数。玩家加入哪些社群，需要先取社群列表，再对每个社群读成员列表判断当前玩家是否在内。社群数量不多时可行；数量增长后需要后端提供按玩家过滤的入口。

成员只返回 `actor_kind` 与 `actor_id`，不含玩家显示名。显示名需另查 `PlayerView`。

### 3.2 会话与参与者

会话列表仍用公开接口 `GET /api/communities/{community_id}/conversations`，返回该社群全部会话，不按玩家过滤。

参与者通过管理接口取得：

```text
GET /internal/communities/{community_id}/conversations/{conversation_id}/members
```

返回 `Page_MemberInterval_`，每个区间含 `membership_id`、`actor_kind`、`actor_id`、`joined_after_sequence`、`left_at_sequence`（可空）。

**这是对上一版请求的替代方案。** 上一版请求给 `ConversationView` 增加参与者字段，后端选择了独立资源。前端按此实现，不要求后端再改。

需要注意区间语义：`joined_after_sequence` 与 `left_at_sequence` 表示成员关系覆盖的消息序号范围，而不只是"当前成员"。因此可以判断某个会话在某一序号区间内是否包含当前玩家，比单一成员列表更准确。私有消息的可见性判断依赖这些区间，前端不自行推断。

会话详情可用 `GET /internal/communities/{community_id}/conversations/{conversation_id}`，含 `next_sequence`。

### 3.3 管理页面所需的对象定位

原先列为 P1 的"管理接口契约及实现"已完整提供，管理员端页面可直接使用：

| 需求 | 接口 |
|---|---|
| 消息定位 | `GET /internal/communities/{cid}/conversations/{vid}/messages` 分页概要，详情含完整消息、实际受众与追踪编号 |
| 轮次定位 | `GET .../conversations/{vid}/turns` 概要，详情含参与决定、任务编号与输入消息编号 |
| 任务列表 | `GET /internal/communities/{cid}/tasks`，可按会话、角色、状态筛选 |
| 冻结输入与审核 | `GET /internal/characters/{character_id}/tasks/{task_id}` 与 `.../context`，必填 `community_id` |
| 执行追踪 | `GET /internal/traces/{correlation_id}`，必填 `community_id`，可选 `character_id` |
| 记忆结果 | `GET /internal/communities/{cid}/characters/{kid}/memory/{collection}`，`collection` 为 segments、digests、entries、entities、edges |
| 反思运行 | `GET .../reflection/runs` 列表与详情，节点输入另有 `.../nodes/{node_task_id}/input` |
| 关系与状态 | `GET .../relationships`、`.../relationships/{target_kind}/{target_id}/evidence`、`.../states` |

追踪查询现在必须提供 `community_id`，可选 `character_id`；非法归属与不存在的关联返回 404。

### 3.4 管理操作

原先"先明确业务入口再实现"的要求已满足，全部复用正式服务：

| 操作 | 接口 | 完成语义 |
|---|---|---|
| 材料封段 | `POST .../characters/{kid}/conversations/{cid}/segments` | 200，返回 `outcome` 与实际段详情；受材料预算约束，终点可能小于请求终点 |
| 安排段反思 | `POST .../reflection/segments` | 202，返回图概要；相同来源可能返回已存在的图 |
| 安排连续性压缩或长期整理 | `POST .../reflection/summaries` | 202；`consumer` 只允许 `continuity_compress` 与 `memory_organize` |
| 失败图重新启动 | `POST /internal/reflection/runs/{graph_run_id}/restart` | 202；只支持 `failed` 且无最终审核结果的图 |

封段与摘要安排的 202 只表示完成安排，执行情况通过图查询读取。**页面不得把 202 显示为已完成。**

### 3.5 范围化材料导出

`POST /internal/communities/{cid}/conversations/{vid}/export`，请求含 `first_sequence`、`through_sequence` 与可选 `character_id`。返回 JSON 正文与下载文件名 `echo-commons-materials.json`，服务器不创建导出文件。

导出是真人测试材料的来源。前端需要提供下载入口，并按角色范围导出以获得该角色真实可见的材料。

### 3.6 两种分页协议不可混用

| 场景 | 结构 | 结束标志 |
|---|---|---|
| 玩家消息读取 | `messages`、`cursor`、`has_more` | 无新消息时保存返回的游标 |
| 管理列表浏览 | `items`、`cursor`、`has_more` | `has_more=false` 时 `cursor=null` |

管理游标绑定查询种类、社群、角色、会话及筛选条件，更换范围或筛选后必须回到第一页。无效或错用游标返回 400。

前端两种分页需用不同的查询键与解析逻辑，不能共用一套。

## 4. P1 玩家维度的会话列表

### 操作范围

按当前玩家读取其参与的会话。用于用户端会话列表。

### 现状

会话列表只能取 `GET /api/communities/{community_id}/conversations`，返回该社群全部会话，不按玩家过滤。前端需对每个会话读取成员区间，判断当前玩家是否在有效区间内，才能筛出属于自己的会话。

会话数量增加后，每个会话一次成员请求不可接受。

### 建议路径

```text
GET /api/conversations?player_id=<id>&community_id=<可选>
```

### 请求

`player_id` 必填，`community_id` 可选用于限定范围。

### 响应

`ConversationView` 数组，并包含当前玩家在该会话中的成员状态，使前端不必逐个查询成员。

### 可见范围

返回该玩家有效成员区间内的会话。私有消息的存在不能通过列表泄露。

### 完成语义

读取操作，无副作用。

## 5. P1 `/api` 侧的会话成员读取

### 操作范围

在公开接口范围读取会话参与者，避免用户端依赖管理路径。

### 现状

会话成员只能通过 `/internal/communities/{community_id}/conversations/{conversation_id}/members` 取得。该路径属于本地管理接口，文档说明其供管理使用、且管理数据缓存需与玩家消息读取身份分别维护。

前端目前按最小范围使用该路径：只读成员身份用于会话列表显示，不读消息正文、记忆或诊断。这满足功能需要，但让玩家界面触及管理范围。

### 建议路径

```text
GET /api/conversations/{conversation_id}/members?player_id=<id>
```

### 请求

`player_id` 必填，用于校验调用者对该会话的可见性。

### 响应

成员区间数组，含 `actor_kind`、`actor_id`、`joined_after_sequence`、`left_at_sequence`。

### 可见范围

调用者必须是该会话的有效成员。私有消息内容不进入该响应。

### 完成语义

读取操作，无副作用。

## 6. P2 未读与最后消息摘要

### 操作范围

维护并读取会话层面的未读标记与最近消息摘要。

### 现状

消息读取是基于游标向前的增量读取，没有未读概念。契约已说明合法私有缺口存在，因此未读不能简单用最大序号差计算。

### 建议路径

```text
GET  /api/conversations/{conversation_id}/state
PUT  /api/conversations/{conversation_id}/read
```

### 请求

读取与标记已读都需要 `player_id`。

### 响应

未读数量、最近一条可见消息的 `message_id` 与时间，以及用于列表展示的摘要字段。

### 可见范围

未读数量按读取玩家分别计算。私有消息只对该玩家可见，不能影响其他参与者的未读数。摘要只能取该玩家可见的消息。

### 完成语义

标记已读为幂等操作，重复调用返回当前状态。

## 7. P2 角色形象字段

### 操作范围

为人物模板增加可选的形象标识，使前端在具备资产时渲染头像而无需改动页面。

### 现状

`BlueprintView` 为 `blueprint_id`、`display_name`、`content_version`、`status`；`CharacterView` 为 `character_id`、`community_id`、`blueprint_id`、`blueprint_version`、`availability_status`、`availability_version`、`created_at_utc`。两者均无形象字段，契约中也没有任何头像或图片字段。

### 建议字段

在 `BlueprintView` 与 `CharacterView` 增加可选、默认为空的 `avatar`。字段值形式由后端决定，前端按"有值则渲染、无值则回退"处理。

### 请求

不涉及新接口，角色创建与社群创建请求不变。

### 响应

两个视图增加 `avatar` 字段；为空表示不使用图片资产。

### 可见范围

与对应模板和角色实例的可见范围一致，不引入额外权限。

### 完成语义

字段缺失或为空都不影响现有行为。

### 需要后端明确的点

若支持用户自建角色，需要明确该字段由谁填写、是否校验格式、是否允许引用外部地址。前端当前不依赖该字段，具备资产时即生效，因此结构需要先留好。

### 前端约定

前端已按回退链实现：字段有值时渲染图片，否则使用由 `character_id` 派生的背景色加 `display_name` 首字。同一角色的颜色在气泡、头像、提及与棋子标记中保持一致。设计依据见 [页面与交互设计](03-page-design.md) 第 4 节。

## 8. P2 身份相关的错误语义

### 现状

当前错误协议为 `400`、`404`、`409`、`422`、`500`、`503`，契约中没有 `401` 与 `403`，也没有声明授权相关的错误结构或安全方案。这是没有凭据场景下的合理状态。

### 建议

引入凭据后再确定：

| 情况 | 建议状态 | 说明 |
|---|---|---|
| 凭据缺失或无效 | `401` | 沿用 `{"error":{"code","message"}}` 结构 |
| 已认证但对对象无权限 | `404` | 不返回 `403`，避免暴露对象是否存在 |

管理接口文档已说明管理范围验证对象归属、非法归属返回 404，前端按该语义处理即可。

### 前端约定

前端需要一处统一的错误归一入口，把 `401` 转为身份失效的界面提示。请求层已归一两种错误形状，新增状态码时只需扩展该入口。

## 9. P3 写入的乐观并发复核

### 现状

`CommunityView` 已有 `state_version`，`ConversationView` 已有 `membership_version`。管理操作已按状态返回 `409`，例如封段起点与下一条未归段材料不符、重启已恢复的图。

但公开写入路径（加入与离开成员、发送消息）没有要求客户端提交期望版本，因此多用户同时操作时前端无法区分"我的操作过期"与"操作失败"。

### 建议

成员加入、离开等改变成员关系的写入，以及阶段五的活动操作，接收可选的期望版本；不匹配时返回 `409`，`code` 中区分版本冲突与幂等内容冲突。

### 前端约定

前端在统一位置处理 `409`：保留原输入，提示状态已变化并触发重新读取。不在页面各处内联重试。

### 完成语义

不匹配时不得产生任何写入。重复提交相同期望版本的操作返回原结果，不按冲突处理。

## 10. P3 活动对象读取

阶段五接入前需要。完整设计见 [活动接入设计](../../server/docs/design/activity-integration.md)，其中 `create`、`observe`、`legal_actions`、`validate`、`apply`、`summarize` 已确定接口职责。

需要前端能够：列出某社群的进行中活动、读取活动权威状态与状态版本、读取当前主体的观察视图（含私有手牌）、列出合法动作、提交动作、读取活动结果与来源。

前端在 [ADR-0002](adr/0002-scene-rendering-as-view-layer.md) 约定：活动状态由服务端下发，渲染层只呈现，不回写。

## 11. 当前不需要的接口

以下内容前端不依赖，后端不需要为前端实现：

- 逐字输出或流式发言。当前为整体消息提交后轮询读取，前端不显示打字机效果。
- WebSocket 或 SSE 推送。当前轮询可完成真人聊天测试。
- 模型密钥、模型路由或供应商配置。前端不请求模型供应商。
- 玩家账户体系本身。`player_id` 到账户的映射由后端设计，前端只要求当前主体来源集中，见 [ADR-0001](adr/0001-identity-and-server-state-single-source.md)。
- 管理员账户与权限。管理接口文档已说明当前无账户级认证，供本地管理使用。
