# 后端模块索引

模块文档记录模块的现行设计和稳定契约，包括已经实现的行为，以及已经确定但尚未实现的接口和流程。尚未实现的内容必须明确标注状态。跨模块组合和持久化规则分别见 [应用组合](../infrastructure/application-composition.md) 与 [持久化和事务](../infrastructure/persistence-and-transactions.md)。

每份模块文档按需要包含：职责和边界、核心对象、输入输出、主流程、状态与失败、持久化、Trace、测试入口。具体字段以代码 Contract、Domain 和 Store 为准，文档说明业务含义和对象责任。开发进度与实施步骤统一记录在 [`implementation-status.md`](../implementation-status.md) 或临时 `design-drafts/` 中。

| 模块 | 文档 | 入口 |
|---|---|---|
| Conversation | [conversation.md](conversation.md) | 消息、输入批次、角色回复 |
| Reflection | [reflection.md](reflection.md) | GraphRun、节点、Artifact、审核和事实提交 |
| Memory | [memory.md](memory.md) | 段、记忆、Thought、搜索和来源 |
| 状态与关系 | [state-and-relationship.md](state-and-relationship.md) | 角色状态、关系证据和确定性规则 |
| Identity | [identity.md](identity.md) | 角色内容、能力和模型输入身份 |
| Agent Harness | [agent-harness.md](agent-harness.md) | 模型与工具的连续调用、输出修正和运行结果 |
| Model Gateway | [model-gateway.md](model-gateway.md) | Provider、模型请求和用量 |

基础设施文档：

- [持久任务运行时](../infrastructure/durable-task-runtime.md)
- [Agent Contract 与模型运行时](../infrastructure/agent-runtime.md)
- [可观测基础设施](../infrastructure/observability.md)
