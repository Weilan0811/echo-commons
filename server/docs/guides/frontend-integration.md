# 前端接入步骤

## 1. 创建或选定对象

按 [HTTP 参考](../reference/http-api.md) 依次创建社群、注册玩家、把玩家加入社群、列出模板、创建角色实例、创建会话。记录后端返回的真实标识，不根据显示名字推断对象。direct 为一个玩家和一个角色，group 接受明确非重复成员。

创建群聊正文示例：

```json
{"kind":"group","conversation_id":"room-1","actors":[{"kind":"player","actor_id":"alice"},{"kind":"character","actor_id":"jin-a"},{"kind":"character","actor_id":"jin-b"}]}
```

标识应先通过对应接口建立。前端选择当前玩家身份；每次读取及发送明确 player_id。跨站开发时在 server.cors_origins 写入前端完整来源。

## 2. 发送与显示

每次新输入生成独立 client_message_id，网络重试保持原标识和原字段。返回 202 后按 message_id 和 sequence 展示已接受消息，不等待模型同步回应。玩家几秒内连发会进入窗口批次；窗口是服务器运行规则，界面无须自行模拟它。

私有消息设 visibility=recipients 并列出 ActorRef；mentions 表示提及，不能代替受众。reply_to_message_id 关联实际可见消息。一次角色回应保存一条完整消息，界面可以按显示需要切成多个气泡，但不向后端逐个发送气泡。

## 3. 两种轮询

messages 返回 messages、cursor、has_more。首次不传 cursor，之后原样使用；has_more=true 继续翻页，即使当前页经过过滤没有消息。新消息按 message_id 去重。切换玩家或会话时清除游标及相应界面数据，避免混入其他读取身份的缓存。

turns 返回可见轮次和参与决定，用于显示谁被安排回应、谁沉默或失败。选择顺序不等于发言完成顺序。轮次完成仍可能没有角色消息，不能把这当成网络故障。当前使用 HTTP 轮询，没有正式 WebSocket、SSE 或 token 流式发言接口。

## 4. 错误与成员变化

400 检查业务输入；422 展示字段错误；404 检查对象标识；409 保留原输入并提示明确冲突；503 可以按界面策略稍后重试同一请求。错误协议具体形状见 HTTP 参考。

加入及离开操作返回 MembershipView。离开期间消息不因重新加入变为可见；旧来源回应也不会发送给新的成员区间。每次请求由后端过滤，前端缓存应按当前读取身份刷新，不能自行补出看不到的私有消息。

## 5. 一个完整界面过程

Alice 选定示例群聊，发送“你们各自有什么建议”，保存 receipt；窗口结束后 turns 显示两位角色 selected。甲先返回一条完整回应，乙随后沉默，轮次 completed。Alice 再向甲发送私有消息；Bob 的消息与轮次查询没有这项来源。内部 context、反思和 traces 属于开发诊断，不放进玩家普通界面。

管理员页面的对象发现、分页、诊断、操作和下载流程见 [本地管理接口](../reference/management-api.md)。管理消息可以包含社群内私人材料，页面的数据缓存与玩家消息读取身份分别维护。
