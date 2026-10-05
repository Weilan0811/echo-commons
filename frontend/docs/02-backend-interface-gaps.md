# 后端接口缺口清单

状态：规划，尚未实现。
更新日期：2026-10-05。
提交方：前端。
接收方：后端。
对接基线：后端已合并的集成分支，含 `d4e19f5`（新消息使用会话范围）与 `ceffe4a`。

本文列出前端仍需依赖、但当前契约未提供的接口。每项按 [推进计划](../../docs/01-project-roadmap.md) 的要求说明操作范围、路径、请求、响应、可见范围与完成语义。

**本文不是已实现能力的清单。** 已实现能力见 [HTTP 参考](../../server/docs/reference/http-api.md) 与 `server/docs/reference/management-api.md`，本文任何条目都不应写入那两份文档。

## 1. 背景：上一版的缺口已全部补齐

上一版列出的六项需求已由后端实现，本轮核对结果：

| 上一版需求 | 现状 |
|---|---|
| P1 社群发现与成员关系读取 | `GET /api/communities` 支持 `player_id` 与 `scope`；`GET /api/communities/{community_id}/members` 读取成员 |
| P1 玩家维度的会话列表 | `GET /api/conversations` 按玩家返回参与的会话 |
| P1 `ConversationView` 补参与者 | `GET /api/conversations/{conversation_id}/membership` 提供成员关系与已读位置 |
| P2 未读与最后消息摘要 | `GET /api/conversations/{conversation_id}/read` 提供 `ReadState` |
| P2 角色形象字段 | `PublicDisplay` 含 `display_name` 与 `avatar_url` |
| P2 `401` / `403` 错误语义 | 仍未实现，见第 4 节 |

因此本文只剩尚未满足的少量需求。

### 本轮契约变化对前端的影响

| 变化 | 内容 |
|---|---|
| 消息视图改名 | `MessageView` 改为 `PlayerMessageView`，新增 `sender_display`、`recipients`、`reply_preview` |
| 新消息不再支持指定受众 | `SendMessage` 移除 `visibility` 与 `recipients`，携带任一字段返回 422 |
| 分页改为最新加历史 | `GET /messages/history` 首次不传 `older_cursor` 返回最新可见消息，并给出 `older_cursor` 与 `poll_cursor` |
| 引用可带预览 | `reply_preview` 仅在引用对阅读者可见时返回，含序号、发送者显示信息与短预览 |
| 轮次补充输入 | `TurnView` 增加 `input_message_ids` |

`PlayerMessageView` 仍保留 `visibility` 与 `recipients`，用于表达历史私有消息。已确认这类数据可以删除，前端不恢复对应标记。

## 2. 剩余缺口与优先级

| 优先级 | 需求 | 影响 |
|---|---|---|
| P2 | `401` / `403` 错误语义 | 没有凭据场景，无法表达身份问题 |
| P3 | 写入的乐观并发复核 | 多用户同时操作时前端无法区分冲突与失败 |
| P3 | 活动对象读取 | 阶段五接入前需要 |

## 3. 已实现接口与前端适配

以下是原先列为缺口、现已由后端补齐的能力。前端适配后端既有接口，不要求后端改动。

### 3.1 社群与玩家发现

| 需求 | 接口 | 说明 |
|---|---|---|
| 列出社群 | `GET /api/communities` | 支持 `player_id` 与 `scope`，因此可以按玩家过滤 |
| 读取社群成员 | `GET /api/communities/{community_id}/members` | 分页，返回身份与加入时间 |

### 3.2 会话列表与成员

| 需求 | 接口 | 说明 |
|---|---|---|
| 玩家维度的会话列表 | `GET /api/conversations` | 按当前玩家返回参与的会话 |
| 会话成员与已读位置 | `GET /api/conversations/{conversation_id}/membership` | 一次读取成员关系与 `last_read_sequence` |
| 标记已读 | `PUT /api/conversations/{conversation_id}/read` | 位置只向前推进，幂等 |

会话列表已按玩家过滤，前端不再需要从社群全量列表自行筛选，也不需要依赖管理接口读取参与者。

### 3.3 消息读取的三种语义

契约现有三种消息读取，用途不同，不可混用：

| 用途 | 接口 | 返回 |
|---|---|---|
| 进入会话读最新 | `GET /messages/history` 首次不传 `older_cursor` | 最新可见消息、`older_cursor`、`has_older`、`poll_cursor` |
| 向上翻历史 | `GET /messages/history` 带 `older_cursor` | 历史页，`poll_cursor` 为 `null` |
| 增量轮询 | `GET /messages` 带 `cursor` | `messages`、`cursor`、`has_more` |

首次读取时 `poll_cursor` 建立增量位置；无新消息时保留返回游标继续轮询。空历史仍给出有效 `poll_cursor`。

这解决了上一版指出的问题：此前必须从最早一页翻到末尾才能看到最新消息。

### 3.4 身份与显示信息

`PublicDisplay` 提供 `actor`、`display_name` 与可选 `avatar_url`。消息的 `sender_display` 与 `recipients` 都使用该类型，因此前端不需要自行维护标识到显示名的映射。头像字段已具备，此前预留的回退链可以直接接上。

### 3.5 引用预览

`reply_preview` 在引用对阅读者可见时返回，含序号、发送者显示信息、短预览与时间；不可见引用不返回正文。前端可直接渲染引用上下文，无需额外请求。

## 4. P2 身份相关的错误语义

### 现状

当前错误协议为 `400`、`404`、`409`、`422`、`500`、`503`，契约中没有 `401` 与 `403`。这是没有凭据场景下的合理状态。

### 建议

引入凭据后再确定：

| 情况 | 建议状态 | 说明 |
|---|---|---|
| 凭据缺失或无效 | `401` | 沿用 `{"error":{"code","message"}}` 结构 |
| 已认证但对对象无权限 | `404` | 不返回 `403`，避免暴露对象是否存在 |

### 前端约定

前端需要一处统一的错误归一入口，把 `401` 转为身份失效的界面提示。请求层已归一两种错误形状，新增状态码时只需扩展该入口。

## 5. P3 写入的乐观并发复核

### 现状

`CommunityView.state_version` 与 `ConversationView.membership_version` 已存在，管理操作也按状态返回 `409`。但玩家侧的加入、离开与发送消息没有要求提交期望版本。

### 建议

改变成员关系的写入接收可选的期望版本；不匹配时返回 `409`，`code` 中区分版本冲突与幂等内容冲突。

### 前端约定

前端在统一位置处理 `409`：保留原输入，提示状态已变化并触发重新读取。

### 完成语义

不匹配时不得产生任何写入。重复提交相同期望版本的操作返回原结果。

## 6. P3 活动对象读取

阶段五接入前需要。完整设计见 [活动接入设计](../../server/docs/design/activity-integration.md)。需要前端能够列出进行中活动、读取权威状态与状态版本、读取当前主体的观察视图、列出合法动作、提交动作、读取结果与来源。

前端在 [ADR-0002](adr/0002-scene-rendering-as-view-layer.md) 约定：活动状态由服务端下发，渲染层只呈现，不回写。

## 7. 当前不需要的接口

- 逐字输出或流式发言。当前为整体消息提交后轮询读取。
- WebSocket 或 SSE 推送。当前轮询可完成真人聊天测试。
- 模型密钥、模型路由或供应商配置。前端不请求模型供应商。
- 玩家账户体系本身。`player_id` 到账户的映射由后端设计，前端只要求当前主体来源集中，见 [ADR-0001](adr/0001-identity-and-server-state-single-source.md)。
- 历史私有消息的界面标记。已确认这类数据可以删除，前端不提供创建入口，也不保留显示标记。
