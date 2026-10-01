# ADR-0009：Reflection 独立持久 Worker 边界

> 状态：Accepted  
> 日期：2026-09-17  
> 取代 [ADR-0001](0001-local-sqlite-runtime.md) 中关于“单个后台 Worker”的范围表述；本 ADR 不改变本地 SQLite、单进程和事务外 Agent 调用约束。

## 背景

Reflection 需要在会话回复之外处理封口消息段、阶段材料、角色 thought 和记忆候选。它的模型调用时间、重试节奏和批次提交与 `conversation.reply` 不同；如果共用会话 Worker 的领取循环，会让记忆整理阻塞玩家回复，也会把两种任务的租约和结果语义混在一起。

## 决策

1. Reflection 使用独立的 `reflection_graph_runs`、`reflection_node_tasks`、`ReflectionGraphTaskStore` 和 `ReflectionWorker`。会话仍使用 `conversation_tasks`、`ConversationTaskStore` 和 `ConversationWorker`。
2. 两个 Worker 共享同一个 `ConversationRuntime`、SQLite 文件、通用 `TaskDispatcher` 外壳和 Trace outbox，但各自拥有任务 Registry、Worker ID、唤醒事件和单任务执行循环；内存事件只负责唤醒，不能替代数据库任务事实。
3. Reflection Agent 调用在写事务外执行。提交前必须重新读取任务、角色状态、关系、记忆来源和窗口版本；节点结果先保存为内部 Artifact，图汇聚后通过共享 Envelope Reviewer 与 Reflection 批次 Reviewer，在一个短事务内整批写入已审核事实、结果决定、处理进度和 Trace outbox。
4. Reflection 不能复用会话的 `AgentResult`、公开消息提交或会话回复提交路径；批次结果保存在 `reflection_results`，角色 thought、日记、记忆、状态、关系和图索引按各自领域 Repository 写入。核心记忆和关系态度描述是否刷新由独立策略判定，不因事实提交自动刷新。
5. 当前部署仍是单进程、单 Conversation Worker 加单 Reflection Worker。就绪检查把两个 Worker 的启动和运行状态都纳入；需要多进程或多主机调度时，必须重新评估 SQLite 锁、租约和 Worker 互斥设计。

## 结果

- 记忆整理不会占用会话回复的任务领取循环；任一反思图任务的模型失败可以独立重试和恢复。
- 任务身份、租约 fencing、批次结果和权威事实的边界清楚，进程重启后可以从对应任务表恢复。
- 单进程仍只有一个 SQLite 写入资源；两个 Worker 的短事务可能互相等待，事务必须保持有界，模型调用不得持有写锁。

## 重新评估条件

- Reflection 或会话需要多进程/多主机横向扩展；
- 两个 Worker 的任务吞吐使 SQLite 写锁成为持续瓶颈；
- 需要跨进程的唤醒、调度优先级或独立部署生命周期；
- Reflection 结果需要跨 Agent 协作或新的持久 AgentCatalog。
