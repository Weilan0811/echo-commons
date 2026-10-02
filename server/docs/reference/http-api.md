# HTTP 接口参考

## 1. 边界和共同类型

此文描述当前实际接口。完整逐字段类型、必填项、数组、枚举和响应结构保存在直接从应用生成的 [OpenAPI 契约](openapi.json)。启动后 `/docs` 提供交互说明，`/openapi.json` 提供同样的机器契约。生成不启动生命周期或调用模型。

请求使用 JSON，未知请求字段拒绝。ActorRef 为 `{"kind":"player","actor_id":"alice"}`，kind 为 player 或 character。成员路径中的 actor_kind 使用同样的枚举。时间为带时区 ISO 8601，正式存储使用 UTC。当前为本地单进程服务，没有玩家账户认证，player_id 明确表示读取或发送主体。

## 2. 全部公开接口

| 方法与路径 | 请求字段或查询 | 成功响应 |
|---|---|---|
| POST /api/communities | name 必填；timezone 默认 UTC；community_id、world_time_utc 可选 | 201 CommunityView |
| POST /api/players | display_name 必填；player_id 可选 | 201 PlayerView |
| PUT /api/communities/{community_id}/players/{player_id} | 无正文 | 200 两个身份字段 |
| GET /api/blueprints | 无 | 200 BlueprintView 数组 |
| POST /api/communities/{community_id}/characters | blueprint_id 必填；character_id 可选 | 201 CharacterView |
| GET /api/communities/{community_id}/characters | 无 | 200 CharacterView 数组 |
| POST /api/communities/{community_id}/conversations | kind、actors 必填；conversation_id 可选 | 201 ConversationView |
| GET /api/communities/{community_id}/conversations | 无 | 200 ConversationView 数组 |
| PUT /api/conversations/{conversation_id}/members/{actor_kind}/{actor_id} | 无正文 | 200 MembershipView |
| DELETE /api/conversations/{conversation_id}/members/{actor_kind}/{actor_id} | 无正文 | 200 MembershipView |
| POST /api/conversations/{conversation_id}/messages | SendMessage，见下表 | 202 MessageReceipt |
| GET /api/conversations/{conversation_id}/messages | player_id 必填；cursor 可选；limit 默认 50，1—200 | 200 MessagePageView |
| GET /api/conversations/{conversation_id}/turns | player_id 必填；limit 默认 50，1—200 | 200 TurnView 数组 |

没有公开社群暂停、会话归档、角色状态写入、活动或反思手动执行接口。领域服务存在不等于 HTTP 已提供这些操作。

## 3. 消息与增量读取

| SendMessage 字段 | 规则 |
|---|---|
| player_id | 非空发送玩家 |
| client_message_id | 非空；同一玩家的客户端幂等身份 |
| text | 非空完整文本 |
| visibility | conversation 或 recipients，默认 conversation；recipients 表示私有受众 |
| recipients | ActorRef 数组；私有消息实际指定受众 |
| mentions | ActorRef 数组；默认空 |
| reply_to_message_id | 可选，必须是发送者可见的合法回复来源 |

MessageReceipt 含 message_id、conversation_id、sequence、trace_id。202 表示消息已接受，角色回应由后台独立完成。重复发送使用相同客户端标识和相同内容，返回原事实；内容冲突返回 409，窗口不因此延长。

MessageView 含 message_id、conversation_id、sequence、sender、text、visibility、mentions、reply_to_message_id、source_turn_id、created_at_utc。不会返回 Thought、角色记忆、模型提示或内部状态。

MessagePageView 为 messages、cursor、has_more。客户端将 cursor 原样交回，不解析内部编码。游标绑定社群、会话、玩家及已扫描序号，不绑定成员版本；每次读取重新按实际成员区间过滤。换玩家或会话时不能复用。无效游标返回 400，可从头重新读取并按 message_id 去重。无新消息时保存返回游标。has_more=true 时继续取下一页；没有更多时等待再请求。limit 限制扫描消息数，过滤后本页可能为空且仍有下一页。合法私有缺口不会要求客户端补齐每个序号。

## 4. 其他响应字段

| 类型 | 全部展示字段 |
|---|---|
| CommunityView | community_id、name、timezone、world_time_utc、status、state_version、created_at_utc、updated_at_utc |
| PlayerView | player_id、display_name、created_at_utc |
| BlueprintView | blueprint_id、display_name、content_version、status |
| CharacterView | character_id、community_id、blueprint_id、blueprint_version、availability_status、availability_version、created_at_utc |
| ConversationView | conversation_id、community_id、kind、status、membership_version、created_at_utc |
| MembershipView | membership_id、community_id、conversation_id、actor、joined_at_utc、left_at_utc |
| TurnView | social_turn_id、conversation_id、status、created_at_utc、completed_at_utc、participation |
| ParticipationView | character_id、reason_code、selection_order、status、outcome |

轮次读取按玩家实际可见来源过滤。selection_order 是规划选择次序，不保证模型完成顺序。未参与、沉默和失败可通过 reason_code、status、outcome 区分；具体枚举在 OpenAPI 中。

## 5. 错误、内部接口和健康

| 状态 | 实际格式与含义 |
|---|---|
| 400 | `{"error":{"code":"invalid_request","message":"..."}}`，业务输入无效 |
| 404 | 同一 error 结构，业务对象不存在，code 来自具体错误 |
| 409 | 同一 error 结构，幂等内容、成员、来源或状态冲突 |
| 422 | FastAPI 默认 `detail` 数组，请求字段或查询参数校验失败 |
| 500 | invalid_response 或 storage_unavailable，内部响应/非重试存储故障 |
| 503 | storage_unavailable，可重试存储故障；ready 的 503 使用健康结构 |

OpenAPI 自动列出的 422 不包含全部运行错误，上表补充实际异常映射。

GET `/internal/characters/{character_id}/tasks/{task_id}/context` 必须提供 community_id；GET `/internal/reflection/runs/{graph_run_id}` 必须提供 community_id、character_id；GET `/internal/traces/{correlation_id}` 返回 correlation_id 和 traces。内部诊断验证明确业务归属，但当前没有账户级认证；供本地开发使用，不能作为玩家数据查询入口。

GET `/health/live` 返回 status=ok、service、version；GET `/health/ready` 返回 status、database、workers_enabled、workers，健康时 200，否则 503。关闭 Workers 的设置允许无需后台工作状态通过数据库就绪检查。两者不请求模型。

## 6. 实际请求例子

已有示例数据时，向群聊发送公共消息：

```http
POST /api/conversations/example-conversation/messages
Content-Type: application/json

{"player_id":"example-alice","client_message_id":"alice-001","text":"大家想聊什么？"}
```

私有消息使用实际角色身份：

```json
{"player_id":"example-alice","client_message_id":"alice-002","text":"这个问题只想问你。","visibility":"recipients","recipients":[{"kind":"character","actor_id":"example-jin-one"}]}
```

随后读取 `/api/conversations/example-conversation/messages?player_id=example-alice` 和 `/api/conversations/example-conversation/turns?player_id=example-alice`。完整创建顺序和前端处理见 [接入指南](../guides/frontend-integration.md)。
