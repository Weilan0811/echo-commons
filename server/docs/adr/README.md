# Architecture Decision Records

本目录记录会长期影响后端边界、数据、部署或权限的决策。模块当前实现见 [后端架构](../architecture.md)、[实现状态](../implementation-status.md) 和 [模块索引](../modules/README.md)。

| ADR | 状态 | 当前决策 |
|---|---|---|
| [0001](0001-local-sqlite-runtime.md) | Accepted | 本地 SQLite、单进程 Runtime 和持久化工作流 |
| [0002](0002-agent-proposal-authority.md) | Accepted | Agent 只有提案权，Runtime 才能提交事实 |
| [0003](0003-agent-framework-boundary.md) | Accepted | Echo 拥有 Agent Contract 和权威状态，Harness/Provider 只能处于边界内 |
| [0004](0004-remove-m0-agent-compatibility.md) | Accepted | 删除 M0 Agent 兼容层，统一 Agent Contract 和 Handler |
| [0005](0005-embedded-vector-retrieval.md) | Accepted | SQLite 内嵌 FTS5 和向量检索，保留结构化检索基线 |
| [0006](0006-model-provider-selection.md) | Accepted | 模型使用逻辑档位和 Model Gateway，Prompt 按稳定度排列 |
| [0007](0007-conversation-batching-and-response-eligibility.md) | Accepted | 输入批次、回复资格和会话任务分开管理 |
| [0008](0008-remove-legacy-m0-persistence.md) | Accepted | 删除 M0 持久化表，保留消息历史 |
| [0009](0009-reflection-worker-boundary.md) | Accepted | Reflection 使用独立 Worker 和图运行任务 |
| [0010](0010-unified-reflection-runtime-contract-freeze.md) | Accepted | 统一 Graph Runtime、Agent Contract、事实提交和模块边界 |

Accepted ADR 的决策发生变化时新增 ADR，本文只维护索引和当前状态。
