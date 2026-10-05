# 前端接入步骤

## 1. 身份、社群与会话

通过 `/api/players` 选择或注册本地测试玩家，记录实际 player_id。创建社群时提供该玩家，服务器同时加入发起者；其他玩家使用正式社群加入路径。随后创建角色和会话，两种创建都提供 player_id，创建会话还要求发起者位于 actors 中。

```json
{"player_id":"alice","kind":"group","conversation_id":"room-1","actors":[{"kind":"player","actor_id":"alice"},{"kind":"character","actor_id":"jin-a"},{"kind":"character","actor_id":"jin-b"}]}
```

示例身份先通过对应创建入口建立。使用 `/api/communities` 和 `/api/conversations` 的后端分页选择对象，直接链接通过会话详情恢复。读取社群公共成员用于创建会话，读取会话当前成员用于受众与提及。名字与头像采用公共投影；缺少头像时由页面提供回退展示。

## 2. 打开最新消息、向上翻页与轮询

首次读取 `.../messages/history?player_id=alice`，展示返回 messages，保存 older_cursor 和 poll_cursor。向上滚动只使用 older_cursor；返回的后续历史页 poll_cursor 为空，不覆盖增量位置。新消息使用 `.../messages?player_id=alice&cursor=...`，接续首次 poll_cursor。

增量 has_more=true 时立即继续下一页，过滤后的空页仍可有下一页；没有新消息时保留返回 cursor 等待。历史 has_older=false 时结束向上翻页。对象列表的 items、cursor、has_more 使用独立协议与查询缓存。

所有消息按 message_id 去重。切换玩家或会话时清除对应游标和身份缓存。私人消息不会要求前端补齐每个序号；单条读取和 reply_preview 用于引用展示，不可见引用不补读管理正文。

## 3. 发送、轮次与已读

新输入生成 client_message_id，网络重试保留原标识与原字段。202 表示接受完成，角色在后台执行。visibility=recipients 指定私有受众，mentions 表示提及，reply_to_message_id 引用自身可见消息。一次角色发言是完整消息，页面可以按展示需要分气泡。

轮次的 input_message_ids 对应当前发送来源，参与状态区分等待、完成、沉默和失败。后台失败不自动重新发送已接受的玩家消息。

会话概要直接提供最后预览、未读及当前成员状态。玩家实际查看消息后提交 `PUT .../read`，正文是 player_id、through_message_id。读取和轮询不提交已读；空历史无需提交。服务器处理两个标签页的较旧位置。

## 4. 成员操作与冲突

自身重新加入使用 `PUT .../membership`，正文提供 player_id、client_operation_id。自身退出使用 DELETE 同路径，查询提供 player_id、expected_membership_id、client_operation_id。首次参加由创建或管理加入建立。

网络重试保持同一操作编号及内容。返回原结果后，如需当前成员状态重新读取会话详情。成员版本或区间冲突时保留输入并刷新状态；内容冲突不能自动更换编号重试。离开期间的消息不会因重新加入变为可见。

400 检查输入或重新读取第一页；404 停止展示不可读取对象；422 展示字段错误；409 使用具体错误码；503 依据现有请求策略处理。完整路径与字段见 [HTTP 参考](../reference/http-api.md)。

## 5. 管理与缓存

管理端使用 `/internal/communities/{community_id}/characters` 和 `.../conversations` 的独立完整列表。通用成员操作只在管理路径，必须提交 expected_membership_version 与 client_operation_id。私人消息、冻结上下文、记忆和恢复诊断使用 [管理参考](../reference/management-api.md)，保持独立查询缓存。

当前使用 HTTP 轮询，没有新增实时推送或流式发言接口。跨域开发设置 server.cors_origins，服务保持既有监听配置。
