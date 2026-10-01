# ADR-0010：统一反思图 Runtime 与 Agent Contract

> 状态：Accepted
> 日期：2026-09-20
> 当前模块：[Reflection](../modules/reflection.md)、[Agent Contract](../infrastructure/agent-runtime.md)、[持久化与事务](../infrastructure/persistence-and-transactions.md)

## 决策

1. Reflection 使用固定图定义、GraphRun、NodeTask、Artifact、ReflectionBatch 和图级审核结果。当前不建设通用动态图引擎。
2. `GraphRun` 拥有图身份、来源范围、拓扑、执行代数和图级状态；`NodeTask` 拥有节点依赖、租约和尝试次数；Artifact 只保存节点输出；GraphResult 只保存聚合结果和审核决定。
3. `AgentInvocation` 只描述一次 Echo-native Agent 调用。它不拥有图调度、租约、Artifact 或事实提交。
4. `ProposalEnvelope` 只保留 `proposal_id`、`kind`、`origin` 和 `payload`。常规对话使用 invocation origin，图级反思使用 graph origin。
5. 节点动作先写 Artifact，再由 Runtime 归一化成候选，聚合为 `ReflectionBatch`，通过统一 Proposal Envelope 审核后生成 ChangeSet 并提交事实。
6. Agent 不生成身份、时间、来源版本、关系证据类别和事实版本。Runtime 负责这些值的生成、校验和提交。
7. Echo-native 是唯一 Agent Loop。Model Gateway 是 Provider SDK 唯一入口。
8. GraphRun、NodeTask、Artifact、GraphResult 使用 `0015_reflection_runtime_rebuild.sql` 建立的四张最终表；旧反思表不再被运行时代码访问。
9. ApplicationRuntime 只负责组合；业务服务通过 Conversation、Reflection、Memory 和 Observability 模块端口接收依赖。
10. Trace、运行日志和 Debug Capture 是可插拔观测部件，不能成为业务流程的必要依赖。

## 固定图范围

Domain 只登记以下图类型：`segment_reflect`、`continuity_compress`、`memory_organize`、`diary_compose`、`view_refresh`。正式触发器按模块实现；当前纵向入口是 `segment_reflect`。

## 结果

- 图运行可以独立重试、恢复和诊断。
- 同一来源只对应一个 GraphRun 身份；来源改变时创建新运行。
- Agent 输入、节点输出、图聚合和事实提交各有清晰 owner。
- 公开 HTTP/Unity 契约不携带 server-only 的 GraphRun、Artifact 或 Trace 字段。
- 开发数据库可以重建，消息、记忆、状态和关系事实独立保留。

## 重新评估条件

- 需要公开图和节点状态给 Unity；
- 需要多进程、多主机或远程工作流；
- 固定图无法表达已经确认的产品流程；
- Agent Contract 需要跨服务传输；
- 需要恢复旧反思任务为可执行实体。
