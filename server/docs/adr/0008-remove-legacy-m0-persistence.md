# ADR-0008：删除 M0 持久化并保留消息历史

> 状态：Accepted
> 日期：2026-09-06
> 相关模块：[Conversation](../modules/conversation.md)、[Agent Contract 与模型运行时](../infrastructure/agent-runtime.md)
> 相关决策：[0004 删除临时 M0 Agent 兼容层](0004-remove-m0-agent-compatibility.md)、[0007 会话批次与回复资格](0007-conversation-batching-and-response-eligibility.md)

## 1. 背景

Runtime 已经只使用 `ConversationTask`、`AgentResult`、`InputBatch` 和参与者关系。旧的 `conversation_turns`、`situation_proposals`、`agent_proposals` 以及 `conversations` 上的角色绑定/阶段摘要列不再参与任何运行时读写，但继续保留会制造错误的数据入口和维护负担。

## 2. 决策

1. 新增不可变的 `0004_remove_legacy_m0_persistence.sql`，删除三个 M0 工作项/Proposal 表；`0001`、`0002`、`0003` 历史 migration 不修改。
2. 在同一 migration 中删除 `conversations.character_id`、`conversations.stage_summary` 和未使用的 `meta.state_version`。角色归属只由 `conversation_participants` 表表达，权威状态版本只由 `world_state.state_version` 表达。
3. 保留 `messages`、`traces` 和 canonical Runtime 表。旧消息仍可作为历史同步数据读取，但其空的 `input_batch_id`/`result_id` 不会被解释为可恢复的 Task 或 AgentResult。
4. 不把旧 Turn 或 Proposal 回填为新 Task/Result；旧工作项和 Proposal 数据随清理 migration 删除。迁移测试必须覆盖已有 0003 数据库和从头安装两条路径。
5. 删除后的数据库由当前版本唯一拥有；旧版本代码遇到更高 Schema 版本必须拒绝启动，不提供旧表兼容路径。

## 3. 结果

- SQLite 只保留当前 Runtime 的事实源，Repository 不需要为历史 M0 表提供兼容分支；
- 旧消息历史不会丢失，但无法从旧 Turn/Proposal 恢复未完成的 Agent 工作；
- `agent_results` 成为唯一的 Agent 结果持久化边界；
- 新增领域持久化必须使用新的 migration，不得重新引入 Turn 或通用旧 Proposal 表。

## 4. 重新评估触发条件

- 需要恢复旧 M0 工作项或 Proposal 的审计/导出能力；
- 需要在数据库升级前自动备份、导出或清理用户历史消息；
- 多进程 Runtime 或远程任务系统改变当前 Task/Result 的持久化边界。
