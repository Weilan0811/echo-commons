# 后端接口交付与剩余依赖

更新日期：2026-10-04。状态：玩家与管理 API 修正已实现，页面接入尚未完成。

当前真实契约以 [HTTP 参考](../../server/docs/reference/http-api.md)、[管理接口](../../server/docs/reference/management-api.md) 和 [OpenAPI](../../server/docs/reference/openapi.json) 为准。实施范围和验收见 [接口实施方案](../../docs/02-api-boundary-review.md)，使用顺序见 [前端接入指南](../../server/docs/guides/frontend-integration.md)。本文件记录前端依赖，不重复维护全部接口字段。

## 1. 已提供的聊天与管理能力

| 需求 | 实际入口与范围 |
|---|---|
| 本地玩家选择与恢复 | `/api/players` 列表与详情 |
| 社群发现与公共成员 | `/api/communities` 列表、详情与 members，按 player_id 检查范围 |
| 玩家会话列表与直接打开 | `/api/conversations` 列表与详情，带成员状态、预览、未读和发送资格 |
| 当前会话参与者 | `/api/conversations/{conversation_id}/members`，只对当前成员提供 |
| 最新消息与历史 | messages/history 首次直接取得最新可见页，older_cursor 读取更早，首次 poll_cursor 建立增量位置 |
| 引用与单条消息 | 消息详情与可见 reply_preview，玩家不补读管理正文 |
| 已读记录 | PUT .../read，按玩家保存单调位置 |
| 自身成员操作 | PUT、DELETE .../membership，使用实际区间及 client_operation_id |
| 公共角色形象 | display_name、avatar_url 绑定模板版本；头像可空 |
| 轮次来源与冲突代码 | input_message_ids、具体幂等和成员冲突代码 |
| 管理独立列表与成员操作 | `/internal` 社群角色、会话列表及指定主体成员路径 |
| 私人材料与运行诊断 | 既有任务、追踪、关系、记忆、反思、操作与导出；已补充正式恢复历史 |

创建社群、角色和会话提供发起 player_id，发起者包含在会话 actors 中。旧公开社群全量会话读取和通用成员写入已移除。玩家页面全部使用 `/api`，管理对象发现和私人缓存独立维护。

## 2. 前端接入要求

- 聊天与管理页面仍需实际实现；接口完成不表示页面适配完成。
- 生成类型从当前 OpenAPI 同步；页面按 player_id、社群、会话和筛选维护缓存。
- 对象列表、消息增量和历史分别处理游标，不混用结束条件。
- 服务端概要负责预览、可见排序和未读；页面仅在实际查看消息时提交阅读位置。
- 成员请求保留原客户端操作编号，旧区间冲突后读取当前状态；消息后台失败不自动重发玩家消息。
- 角色头像组件和颜色回退仍待前端实现，不把字段提供写成组件完成。

## 3. 独立后续依赖

| 需求 | 安排 |
|---|---|
| 玩家账户与管理权限 | 远程部署前确定身份凭据、401/403 和访问策略；当前为本地测试身份 |
| 活动列表、观察与行动 | 随实际玩法与 [活动设计](../../server/docs/design/activity-integration.md) 实施；不公开内部 validate/apply 步骤 |
| 人工评价、长期生活和更多管理写入 | 按对应阶段的真实业务与存储契约安排 |

当前轮询支持完整消息，不新增 WebSocket、SSE 或逐字输出。模型密钥、供应商路由和完整模型捕获不进入前端接口。
