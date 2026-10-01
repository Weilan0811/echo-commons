# Agent Contract 与模型运行时

## Agent Contract

Echo-native 是当前唯一 Agent 执行路径。一次模型运行使用四层对象：

| 对象 | 作用 |
|---|---|
| `AgentInvocation` | 一次不可变调用的身份、作用域、上下文、输出 Contract、执行策略和 Trace 关联 |
| `AgentRunResult` | 一次 Harness Run 的状态、步骤、用量和互斥输出分支 |
| `ProposalEnvelope` | 送入 Runtime Reviewer 的最小提案边界：`proposal_id`、`kind`、`origin`、`payload` |
| `ReflectionNodeOutput` / `CharacterMessageProposal` | 节点动作或角色回复的类型化内容 |

`AgentInvocation` 不保存图租约、Artifact、节点后继或事实提交字段。常规对话使用 `ConversationScope + ContextSnapshotV2`；反思节点使用 `ReflectionNodeScope + NodeInput`。

## 反思节点输出

节点只返回 `reflection_node.v1` 的动作。Runtime 将动作写成 Artifact，再做以下处理：

```text
Node action
  → ReflectionArtifact
  → ReflectionArtifactNormalizer
  → ReflectionBatch
  → ProposalEnvelope
  → ReflectionReviewer
  → SegmentReflectionChangeSet
```

模型返回简单的来源引用。消息序号、来源版本、时间、ID、图身份和审核字段由 Runtime 补齐或校验。

## 执行与错误传递

| 边界 | 负责内容 | 详细规则 |
|---|---|---|
| `services/model_gateway/` | Provider 请求、供应商错误、单请求重试和用量 | [Model Gateway](../modules/model-gateway.md) |
| `agents/harness/` | Prompt、工具循环、输出修正与 `AgentRunResult` | [Agent Harness](../modules/agent-harness.md) |
| `runtime/` | 审核、任务状态、再次执行和事实提交 | [持久任务运行时](durable-task-runtime.md) |

Provider SDK 不进入 Runtime、Domain 或 Store。错误跨边界时保留稳定错误码和是否可重试的决定；Runtime 根据结果类别安排任务，不用同一个重试计数器覆盖三层。

## 运行约束

- Agent 不读数据库，不持有 Repository，不直接修改游戏事实。
- Runtime 为 Agent 生成 `invocation_id`、时间、ID、版本、来源边界和预算。
- Harness 将模型与工具的执行结果归一为 `AgentRunResult`；Runtime 决定任务再次执行、失败或重新调度。
- Prompt 按稳定内容在前、动态任务在后的顺序构造，以提高前缀缓存命中率。

## 测试入口

- Contract 和 Proposal：`server/tests/test_agent_contracts.py`、`test_reflection_contracts.py`。
- Echo-native Harness：`server/tests/test_agent_harness.py`、`test_xiaojin_character_agent.py`。
- Model Gateway：`server/tests/test_model_gateway.py`。
