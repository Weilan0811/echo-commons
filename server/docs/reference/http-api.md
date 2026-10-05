# HTTP 接口参考

## 1. 共同规则

本文描述当前实际公开接口。逐字段类型、枚举和可空字段见从应用生成的 [OpenAPI](openapi.json)，长期规则见 [玩家 API 设计](../design/player-api.md)。请求正文拒绝未知字段，时间使用带时区 ISO 8601，正式保存为 UTC。

当前为本地测试模式，`player_id` 表示选择的玩家，没有账户认证。ActorRef 为 `{"kind":"player","actor_id":"alice"}`，kind 是 player 或 character；系统消息使用独立 system 来源。公共展示包含 actor、display_name、avatar_url；角色展示绑定实际模板版本。

对象列表返回 items、cursor、has_more，默认 limit=50，范围 1—200；结束时 cursor=null。游标绑定查询种类、玩家与筛选范围。对象不存在或读取范围不符返回 404，存在范围的空列表返回 200。

## 2. 全部公开接口

| 方法与路径 | 请求字段或查询 | 成功响应 |
|---|---|---|
| POST /api/players | display_name 必填；player_id 可选 | 201 PlayerView |
| GET /api/players | 对象列表分页 | 200 Page[PlayerView] |
| GET /api/players/{player_id} | 路径身份 | 200 PlayerView |
| POST /api/communities | player_id、name 必填；timezone 默认 UTC；community_id、world_time_utc 可选 | 201 CommunityView，发起者同时加入 |
| PUT /api/communities/{community_id}/players/{player_id} | 无正文，当前测试玩家加入 | 200 两个身份字段 |
| GET /api/communities | player_id 必填；scope=joined 或 available，默认 joined；分页 | 200 Page[CommunityCard] |
| GET /api/communities/{community_id} | player_id 必填，要求属于社群 | 200 CommunityView |
| GET /api/communities/{community_id}/members | player_id 必填，要求属于社群；分页 | 200 Page[PublicDisplay] |
| GET /api/blueprints | 无 | 200 BlueprintView 数组 |
| POST /api/communities/{community_id}/characters | player_id、blueprint_id 必填；character_id 可选 | 201 CharacterView |
| GET /api/communities/{community_id}/characters | player_id 必填，要求属于社群 | 200 CharacterView 数组 |
| POST /api/communities/{community_id}/conversations | player_id、kind、actors 必填；conversation_id 可选；发起者必须在 actors 中 | 201 ConversationView |
| GET /api/conversations | player_id 必填；community_id 可选；membership=current/past/all，默认 current；status=active/archived/all，默认 active；分页 | 200 Page[PlayerConversationSummary] |
| GET /api/conversations/{conversation_id} | player_id 必填，要求有真实参与历史 | 200 PlayerConversationSummary |
| GET /api/conversations/{conversation_id}/members | player_id 必填，要求当前成员；分页 | 200 Page[PublicDisplay] |
| PUT /api/conversations/{conversation_id}/membership | player_id、client_operation_id 必填；自身重新加入 | 200 MembershipResult |
| DELETE /api/conversations/{conversation_id}/membership | 查询 player_id、expected_membership_id、client_operation_id 必填 | 200 MembershipResult |
| POST /api/conversations/{conversation_id}/messages | SendMessage | 202 MessageReceipt |
| GET /api/conversations/{conversation_id}/messages | player_id 必填；cursor 可选；limit 默认 50，1—200 | 200 MessagePageView |
| GET /api/conversations/{conversation_id}/messages/history | player_id 必填；older_cursor 可选；limit 默认 50，1—200 | 200 MessageHistoryView |
| GET /api/conversations/{conversation_id}/messages/{message_id} | player_id 必填，消息必须可见 | 200 PlayerMessageView |
| PUT /api/conversations/{conversation_id}/read | player_id、through_message_id 必填 | 200 ReadState |
| GET /api/conversations/{conversation_id}/turns | player_id 必填；limit 默认 50，1—200 | 200 TurnView 数组 |

社群全量会话列表及指定任意主体的会话成员操作使用 [管理接口](management-api.md)。玩家读取不需要请求管理路径。社群暂停、世界时间管理、会话归档、活动和手动反思没有新增公开写入入口。

## 3. 消息与三种分页位置

SendMessage 必填 player_id、client_message_id、非空 text。visibility 为 conversation 或 recipients，默认 conversation；私有消息使用 recipients 指定 ActorRef。mentions 默认空，reply_to_message_id 可空，回复来源必须对发送者可见。

MessageReceipt 包含 message_id、conversation_id、sequence、trace_id。202 表示消息接受，后台独立生成回应。相同玩家、客户端标识和内容返回原事实，内容不同返回 409 idempotency_conflict，不延长输入窗口。

PlayerMessageView 包含原消息字段 message_id、conversation_id、sequence、sender、text、visibility、mentions、reply_to_message_id、source_turn_id、created_at_utc，增加 sender_display、recipients、reply_preview。私有 recipients 表达发生时实际接收主体，公共消息为空数组。reply_preview 仅在引用对阅读者可见时提供，包含短预览；不可见引用不返回正文。消息不含 Thought、记忆、模型提示或内部任务状态。

| 协议 | 响应和使用 |
|---|---|
| 对象列表 | items、cursor、has_more；结束 cursor=null；改变筛选回到第一页 |
| 消息增量 | messages、cursor、has_more；一页限制扫描数量，过滤后可以为空且有下一页；无新消息保留返回游标继续轮询 |
| 最新和历史 | messages、older_cursor、has_older、poll_cursor；首次不传 older_cursor，取得最新可见消息；首次 poll_cursor 建立增量位置；后续历史页 poll_cursor=null |

消息均按序号升序显示。历史按可见消息数量限制，固定首次读取终点；更早消息用 older_cursor，新消息用增量 cursor。空历史仍给出有效 poll_cursor。游标原样传递，前端不解析，不能跨玩家、会话或协议使用。

## 4. 会话概要、阅读与成员

PlayerConversationSummary 包含原 ConversationView 字段及 self_membership_status、self_membership_id、can_send、direct_peer、last_message、last_visible_message_at_utc、last_read_sequence、unread_count。预览 text_preview 最多 160 个字符。列表按可见活动排序，不携带全局 next_sequence。

ReadState 包含 conversation_id、last_read_sequence、unread_count。已读请求必须指定实际可见消息；位置只向前推进。未读统计其他主体的实际可见消息；自己的消息、不可见私人消息和离开期间消息不计入。列表、消息和轮询读取不自动标记已读。旧会话初始阅读位置为 0。

MembershipResult 包含实际 membership、操作完成时 membership_version、self_membership_status。重复操作返回原结果；新状态另读会话详情。membership 包含真实成员区间编号、主体、加入离开序号与时间。自身退出绑定 expected_membership_id；管理变更绑定 expected_membership_version。client_operation_id 同内容重复复用，不同内容冲突。直接会话固定原始玩家与角色，双方离开后可以分别恢复。

TurnView 增加 input_message_ids；保留 status、participation 及完成时间。只显示玩家可见来源轮次，selection_order 表示规划次序。沉默、失败和异步回应不触发玩家消息自动重发。

BlueprintView 增加可空 avatar_url。CharacterView 增加 display_name、avatar_url，按实例绑定的模板版本取得。

## 5. 错误与健康

业务错误为 `{"error":{"code":"...","message":"..."}}`，422 保持 FastAPI detail 数组。

| 状态与代码 | 意义 |
|---|---|
| 400 invalid_request / invalid_cursor | 业务输入或游标无效 |
| 404 not_found 或具体对象代码 | 对象不存在或不属于读取、操作范围 |
| 409 idempotency_conflict | 同一消息或成员操作标识用于不同内容 |
| 409 membership_version_conflict | 管理成员版本已经变化 |
| 409 membership_interval_conflict | 自身退出的成员区间已经变化 |
| 409 conversation_archived | 归档不允许发送或加入 |
| 409 conflict | 其他既有业务冲突 |
| 500 invalid_response / storage_unavailable | 内部响应或非重试存储故障 |
| 503 storage_unavailable | 可重试存储故障 |

GET /health/live 返回 status、service、version；GET /health/ready 返回 status、database、workers_enabled、workers，健康时 200，否则 503。两者不请求模型。

接入过程见 [前端指南](../guides/frontend-integration.md)，私人材料和恢复诊断见 [管理参考](management-api.md)。
