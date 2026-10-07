# 后端接口缺口清单

状态：一项待实现，其余已核对解决。
更新日期：2026-10-07。
提交方：前端。
接收方：后端。

本文只列两类内容：前端需要、但当前契约未提供的能力，以及需要后端作出决定的设计问题。已实现的能力见 [HTTP 参考](../../server/docs/reference/http-api.md) 与 [管理接口参考](../../server/docs/reference/management-api.md)，前端的适配方式记在 [前端状态](status.md) 与 [页面设计](03-page-design.md)。

每项按 [推进计划](../../docs/01-project-roadmap.md) 的要求说明操作范围、路径、请求、响应、可见范围与完成语义。

## 1. 契约基线

前端类型由 `server/docs/reference/openapi.json` 生成，核对时为 67 个路径（`/api` 33 个、`/internal` 34 个）、216 个 schema。本文所有字段说明以该文件为准，不在这里复制，避免两处说法不一致。

## 2. 缺口清单

| 优先级 | 需求 | 影响 | 章节 |
|---|---|---|---|
| P3 | 活动对象读取 | 阶段五接入前需要 | 3 |

已核对解决的三项见第 4 节。管理端与用户端因此可以继续实现，不阻塞。

## 3. P3 活动对象读取

阶段五接入前需要，当前契约未提供任何活动端点。完整设计见 [活动接入设计](../../server/docs/design/activity-integration.md)。

需要前端能够列出进行中活动、读取权威状态与状态版本、读取当前主体的观察视图、列出合法动作、提交动作、读取结果与来源。

前端在 [ADR-0002](adr/0002-scene-rendering-as-view-layer.md) 约定：活动状态由服务端下发，渲染层只呈现，不回写。

## 4. 已核对解决

以下三项在前一版列出，现已由后端实现。前端据此继续实现，记录结论以免重复讨论。

### 4.1 会话摘要补显示名称

`PlayerConversationSummary` 增加 `display_name`，同时新增 `self_membership_status`、`self_membership_id` 与 `can_send`。

前端会话列表直接使用 `display_name`，不再显示会话标识，也不再为群聊逐个查询成员。`GET /api/conversations/{conversation_id}/members` 在会话页只用于头像与提及候选。

### 4.2 发言产物结构定义

`ConversationResultView.payload` 按 `status` 声明为 `oneOf` 与 `discriminator`：

| 变体 | 结构 |
|---|---|
| `completed` | `output.contract` 与 `output.payload`；后者含 `utterance`、可空 `thought`、可空 `reply_to_message_id` |
| `no_proposal` | `output` 为 `null` |

产物另含 `steps` 数组，每步有 `step_index`、`response_kind`、`tool_activities`、`usage_summary`、`duration_ms` 与 `diagnostic_codes`。

此前的表述疑问也已澄清：模型返回的 `{"outcome":"silent"}` 转换为 `no_proposal`，通过审核后参与决定才成为 `outcome=silent`。三者分属模型输出、生成结果与参与决定三个层级。

前端按此结构渲染，不再解析无类型 JSON。

### 4.3 Thought 清理策略

机制已实装，语义如下：

- 发言产物不重复保存内心正文，管理查询从独立 Thought 记录读取已审核保存的正文
- 没有记录或已清除时 `thought` 为 `null`，清除时间见 `thought_removed_at_utc`
- `thought_removed_at_utc` 表达的是「数据库中不可查」；显式开启的模型捕获文件独立保存，不随数据库清除而删除
- 玩家消息接口继续不返回内心

前端两种状态都正确呈现：未清除时展示正文，已清除时展示清除时间与说明。

### 4.4 写入的乐观并发复核

管理侧的成员写入已实现：`ManageMembership` 含必填的 `client_operation_id` 与 `expected_membership_version`，不匹配时返回 `409` 并区分版本冲突与幂等内容冲突。

玩家侧未实现，但当前不需要：玩家端只有加入社群这一项成员关系写入，主体是自身，不存在与他人并发冲突的场景。前端在统一位置处理 `409`，保留原输入并触发重新读取。

## 5. 已决定不做

以下事项前端已确认不再需要，后端无需投入实现。

| 事项 | 决定 | 依据 | 后端文档状态 |
|---|---|---|---|
| `401` / `403` 错误语义 | 不做 | 没有凭据场景：玩家标识由使用者指定，管理面只面向部署者本人 | HTTP 参考的错误码表只列实际支持的码，未声称凭据语义 |
| 管理端鉴权与权限模型 | 不做 | 开源部署中每个实例只有部署者可以访问，不存在需要区分的管理角色 | 管理接口参考已新增 1.1 访问边界一节 |
| 管理端写操作的前端入口 | 不做 | 契约保留 5 个写端点，前端不提供界面入口 | 无需改动 |
| 材料导出的界面入口 | 不做 | 只有开发者读取数据，现有命令行已覆盖 | 无需改动 |

管理端访问边界的前端对应处理见 [页面设计的导航与路由一节](03-page-design.md)：不保存凭据、不做权限控制。

## 6. 不需要的能力

- 逐字输出或流式发言。当前为整体消息提交后轮询读取。
- WebSocket 或 SSE 推送。当前轮询可完成真人聊天测试。
- 模型密钥、模型路由或供应商配置。前端不请求模型供应商。
- 玩家账户体系本身。`player_id` 到账户的映射由后端设计，前端只要求当前主体来源集中，见 [ADR-0001](adr/0001-identity-and-server-state-single-source.md)。
- 历史私有消息的界面标记。已确认这类数据可以删除，前端不提供创建入口，也不保留显示标记。