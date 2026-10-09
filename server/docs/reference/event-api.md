# SSE 事件接口参考

本文件描述实际事件接口，长期规则见 [实时通信设计](../design/realtime-communication.md)。接口路径及请求类型见 [OpenAPI](openapi.json)，所有事件 data 的逐字段结构见从后端类型生成的 [事件数据契约](event-data-schema.json)。

## 1. 身份与连接

当前使用本地 player_id 选择玩家；两条入口均要求玩家属于目标社群。每个页面按玩家与社群复用连接，聊天写入、成员操作和阅读位置仍通过原 HTTP 接口执行。社群暂停不关闭事件流。

| 方法与路径 | 参数 | 成功结果 |
|---|---|---|
| GET /api/communities/{community_id}/events/cursor | player_id 必填 | 200 CursorResponse，包含 cursor |
| GET /api/communities/{community_id}/events | player_id 必填；首次提供 cursor；重连可提供 Last-Event-ID 请求头 | 200 text/event-stream |

Last-Event-ID 优先于 cursor 查询参数。游标绑定玩家、社群和扫描位置，不能与消息增量、历史或列表游标互换。响应不缓存；X-Accel-Buffering: no 要求支持该设置的代理即时传递数据。

## 2. SSE 字段与业务事件

事件 id 为不透明恢复游标，event 为事件类型，data 为一个 JSON 对象。事件以空行结束。消息和变化通知都按扫描顺序发送；不同客户端可见的事件不同，因此允许位置间存在缺口。

| event | data | 处理用途 |
|---|---|---|
| conversation.message_created | community_id、conversation_id、message: PlayerMessageView | 按 message_id 合并消息；没有 Thought |
| conversation.turns_changed | community_id、conversation_id | 重新读取可见轮次与接话链 |
| conversation.summary_changed | community_id、conversation_id | 刷新会话详情、列表及未读展示 |
| conversation.members_changed | community_id、conversation_id | 刷新成员和自身成员状态 |
| conversation.read_changed | community_id、conversation_id | 刷新当前玩家阅读位置和摘要 |
| community.status_changed | community_id | 刷新社群运行状态 |
| community.appearance_changed | community_id | 刷新社群封面与列表卡片 |
| character.appearance_changed | community_id、character_id | 刷新角色、参与者与发送者展示 |

变化通知不携带过去某一时刻的完整状态，查询返回当前结果。同一对象的连续通知可以合并刷新。不可见消息不产生针对该玩家的消息或摘要通知；阅读位置变化只通知所属玩家。成员通知保存发生时相关玩家范围，退出者收到自身变化，离开者不接收随后无关的成员变化。

变化通知示例：

```text
id: <恢复游标>
event: conversation.turns_changed
data: {"community_id":"community","conversation_id":"conversation"}

```

消息事件的 message 采用现有完整玩家消息结构，包含正文、发送者展示和可见引用预览。发送者为玩家或角色；字段定义见事件数据契约。接收事件不标记已读，实际阅读后仍调用原阅读位置写接口。

## 3. 控制事件与心跳

| event | data | id 与处理 |
|---|---|---|
| checkpoint | {} | 携带新恢复游标；确认已经扫描的位置，不改变业务数据 |
| resync_required | {"reason":"cursor_expired"} | 不携带 id；关闭旧连接并执行初次同步 |
| access_revoked | {"reason":"membership_required"} | 不携带 id；停止原范围连接与读取 |

经过不可见记录后可以收到 checkpoint，但不会收到被过滤事件的类型或正文。心跳为 SSE 注释，每 15 秒发送一次，不包含 id，不推进事件位置，也不查询消息数据库。

恢复记录保留最近 24 小时，每小时清理。网络发送连续 30 秒不能完成时关闭连接。服务结束事件响应后，EventSource 可能继续自动重连；收到上述终止控制事件时客户端必须显式关闭原连接。

## 4. 首次同步与恢复

1. 读取事件游标 C。
2. 使用现有查询加载列表、消息历史、轮次和社群状态。
3. 以 C 建立事件连接，处理初始化期间的变化和后续通知。

初始查询可能已经包含事件中的消息，按 message_id 去重。浏览器自动重连使用最后收到的 id；页面重新打开可使用保存的游标。重复传输允许发生；事件位置不能替代消息编号、活动版本或玩家已读位置。

收到 resync_required 后重新取得游标，并重新加载当前列表、选定会话最新历史和状态。长时间断线后需要连续补充所有聊天消息时，另用原消息增量游标分页读取；不要把事件保留期当成消息保留期。

## 5. 错误与关闭

建立连接前沿用 [HTTP 错误格式](http-api.md#5-错误内部接口和健康)。缺少初始游标、非法格式、身份范围不符或未来位置返回 400 invalid_cursor；社群不存在或不具有访问资格返回 404。缺少必填请求字段返回 422。

有效但已经清理的游标返回事件流中的 resync_required。建立响应后资格丧失使用 access_revoked；后端或网络故障导致连接结束，由客户端重连并重新接受普通 HTTP 校验。切换玩家或社群、退出页面时关闭连接。
