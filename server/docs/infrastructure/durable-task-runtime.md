# 持久任务运行时

## 职责

通用 Dispatcher 负责恢复过期租约、领取任务、路由 Handler、执行一次任务和报告结果。它不理解会话、反思、角色或记忆规则。

业务任务由两个明确的持久对象负责：

| 任务 | 表和 Store | Worker |
|---|---|---|
| 会话回复 | `conversation_tasks` / `ConversationTaskStore` | `ConversationWorker` |
| 反思节点 | `reflection_node_tasks` / `ReflectionGraphTaskStore` | `ReflectionWorker` |

反思图本身由 `ReflectionGraphRun` 管理。根 GraphRun 直接拥有来源、拓扑、状态、执行代数和恢复行为。

## 状态

GraphRun：`pending → running → retry_wait → completed / partial / failed / cancelled`。

NodeTask：`pending → processing → retry_wait / completed / failed`，条件节点也可以进入 `skipped`。

ConversationTask 使用自己的会话任务状态机，由 `ConversationTaskStore` 和 `ConversationCommitService` 管理。

## 失败重试

当前实现先读取 Harness 返回的 `FailureInfo`，再按恢复动作处理；Harness 内的处理见 [Agent Harness](../modules/agent-harness.md)。

| Harness 结果或 Runtime 情况 | 任务处理 |
|---|---|
| `RETRYABLE`：供应商暂时失败、工具暂时失败、截止时间或来源已变化 | 在任务次数内进入 `retry_wait`；会话重建上下文，反思遵守 GraphRun 的来源版本规则；当前使用 Runtime 的任务退避设置 |
| `FAILED`：凭据、额度、配置、工具权限或相同预算已耗尽 | 记录具体错误码并进入 `failed`，不重新执行同样的调用 |
| 输出通过 Harness 校验、但 Runtime 审核拒绝 | 来源已过期时重新取得上下文；模型可修正的提案错误可在任务次数内再次执行并附审核错误提示；配置或权限错误直接失败 |
| 写入事务失败或租约失效 | 沿用租约恢复与执行代数规则；不能因重试重复提交角色消息或事实 |

任务再次执行会创建新的 `AgentInvocation`，不继承上次用于修正格式的临时 Prompt 消息。对于模型可修正的审核错误，新调用只附稳定审核码和简短修正要求；供应商暂时失败无需修改 Prompt。错误码、类别、建议等待时间、尝试次数和关联 Trace 要随结果传递；不能只保存 `stop_reason`。Provider 单请求重试和 Harness 内修正各自遵守其预算，不消耗持久任务的尝试次数。

- 必需节点自动重试耗尽后进入 `failed`，同时 GraphRun 进入失败状态。
- 可选条件节点自动重试耗尽后保留 `failed`，其他节点继续执行；聚合成功后 GraphRun 进入 `partial`，结果中保存可用候选和失败明细。
- 再次触发相同来源时，Repository 返回已完成、部分完成或正在运行的 GraphRun。
- 已失败的同来源 GraphRun 可以提高 `execution_generation`，将失败节点重新置为 `pending`，再由 Graph Worker 执行。
- 来源范围或来源版本改变时，创建新的 GraphRun。
- 租约代数和执行代数用于拒绝迟到结果；迟到结果不会写 Artifact，也不会改变图状态。

## 失败结果

失败任务保留稳定错误码、尝试次数和 Trace 关联。失败不会伪装成成功，也不会生成空的角色消息或事实。人工或上层触发重新执行时，复用来源身份对应的 GraphRun。

## 测试入口

- 通用 Dispatcher 和 lease：`server/tests/test_dispatcher.py`、`test_task_lease.py`。
- 会话任务恢复：`server/tests/test_runtime_acceptance.py`。
- GraphRun/NodeTask 恢复、同来源和迟到结果：`server/tests/test_reflection_graph_runtime.py`、`test_reflection_runtime.py`。
