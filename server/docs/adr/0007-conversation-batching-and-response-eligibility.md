# ADR-0007：输入批次、回复资格与积压恢复

> 状态：Accepted
>
> 日期：2026-09-05
>
> 实施状态：已实现；领域模型、不变量、SQLite 结构迁移、T1/T2/Agent/T3、Runtime Repository、会话同步和旧持久化清理已完成，canonical Runtime 已切换为 API/Worker 主路径

## 背景

M0 将每条玩家消息直接绑定一个执行回合。现实时间下的短句连发、睡眠、暂忙和剧情消失要求收集输入、等待回复资格与执行任务具有不同生命周期。逐条补答长期积压会产生大量过时回复；直接读取最新历史则可能把后到输入混入旧任务。

前一版设计将多个一对多关系实体化为成员表和关联表，增加了没有独立业务含义的表。重新审查后，按奥卡姆剃刀原则收敛为直接外键关系；只有群聊确实需要的会话参与者多对多关系保留独立表。

## 决策

1. 使用 InputBatch 表示连续输入；每次新消息后静默 6 秒封口，不设单批最长时间。幂等重发不延长截止时间。持续发送会持续等待，这是预期交互。
2. 待回应状态持久化；封口不等于可以调用 Agent。回复资格由 Runtime 根据权威世界状态和角色状态判定，多个阻止条件必须全部解除。
3. 保留本地 SQLite、单 Worker、短事务和会话内串行。等待资格不持有租约、不消耗模型重试；事件只唤醒，持久化查询负责恢复。
4. 使用 ConversationTask 表示一次可恢复的逻辑回复任务。一个 Task 可覆盖多个连续封口批次，批次通过 input_batches.task_id 直接归属 Task，不增加 task_input_batches 关联表。
5. 玩家消息通过 messages.input_batch_id 直接归属 InputBatch。每条玩家消息最多属于一个批次，不增加 input_batch_messages 成员表。
6. T2 冻结任务时记录输入边界、上下文边界和世界／角色状态版本。任务冻结后新输入进入后续批次，不能通过“会话最新 N 条消息”进入当前上下文。
7. Agent 返回的候选载荷和审核状态保存为 AgentResult。Proposal 仍然只有提案权；只有 approved Result 才能在 T3 生成角色 Message。一个 Result 可以物化为零条或多条气泡消息，不增加 logical_replies 或 reply_segments 表。
8. 提交前再次审核资格；若失去资格，Result 过期，Task 延迟，已绑定输入不标记覆盖，恢复后复用同一 Task 重新生成。技术失败采用有限重试，最终失败不阻塞后续输入，也不冒充角色沉默。
9. 同一会话同一时刻最多一个活动 Task；不同会话可以继续调度。会话使用独立 conversation_id；chat_window_id 只属于客户端视图。
10. 多会话使用 conversations 表。由于最终产品支持一个会话包含多个角色，保留 conversation_participants 作为唯一必要的多对多关系表；S2.5 只执行单聊，群聊记录参与者但明确拒绝 Agent 执行。
11. 一个 AgentResult 可以生成多个有序角色 Message，使用 messages.result_id 和 messages.bubble_index 表示同一次逻辑回复及气泡顺序。当前策略只生成一个气泡；延迟投递不在本阶段增加表。
12. 重启按当前现实时间判断资格，不补跑错过的时点；剧情限制必须按剧情条件解除。开场已登记脚本可以采用即时策略，不受普通 Agent 收集延迟强制约束。

## 最小持久化模型

业务表分为三类：

| 类别 | 表 |
|---|---|
| 全局和会话上下文 | world_state、character_states、conversations、conversation_participants |
| Conversation Runtime 核心 | messages、input_batches、conversation_tasks、agent_results |
| 技术基础设施 | traces、schema_migrations，以及数据库元数据 |

核心一对多关系直接使用外键：

~~~text
InputBatch 1 ─── N PlayerMessage
Task       1 ─── N InputBatch
Task       1 ─── N AgentResult
Result     1 ─── N CharacterMessage
~~~

不新增 input_batch_messages、task_input_batches、logical_replies、reply_segments、response_eligibility 或 context_snapshots 表。状态版本、冻结边界、尝试次数和气泡序号都是现有实体的字段或内存值对象。

## 取舍与范围

不引入外部消息中间件，也不增加一套长期旧版 Runtime。以测试保护行为，迁移和必要适配集中处理，新路径切换后删除临时分支。既有 migration 不改写。

无限收集时间可能延迟回复；无限积压可能超出上下文容量。容量不足必须保留输入并报告受控等待，不得只读取尾部却将全部标记为已覆盖。摘要和输入分段准备留有接口，算法由后续记忆与巩固模块实现。

作息、剧情规则内容、多 Agent 群聊仲裁、跨会话记忆、延迟投递、自然拆句优化和输入长度／成本安全防护不在本阶段实现。

本 ADR 扩展 [ADR-0001](0001-local-sqlite-runtime.md) 的持久化工作项语义，保留其部署决策；继续遵守 [ADR-0002](0002-agent-proposal-authority.md) 的提案权和提交权边界。

具体 as-built 状态、事务、数据约束与验收以[Conversation 模块文档](../modules/conversation.md)和[后端实现状态](../implementation-status.md)为准。
