# Conversation 模块

## 职责和边界

Conversation 模块负责把玩家消息变成一次可执行的角色回复任务，并把经过审核的回复写回消息历史。它拥有消息顺序、输入批次、回复任务、Agent 结果和同步游标所需的 Runtime 流程。

模块入口位于 `runtime/conversation/`，由 `ConversationModule` 组合 Repository、上下文构建器、Agent 和提案审核器。API 只负责把 HTTP DTO 映射为命令或查询；Agent 只返回候选结果；权威事实由 Conversation Runtime 在短事务中提交。

Conversation 不负责记忆段摘要、角色长期状态或玩家关系规则。角色回复附带的 `Thought` 由本模块在批准回复的同一提交事务中交给 Memory Repository 保存，Thought 的来源和后续归段由 Memory 模块负责。

## 核心对象和持久化

| 对象 | 作用 | 主要表或来源 |
|---|---|---|
| `Conversation` | 会话身份、类型、可执行状态和上下文版本 | `conversations` |
| `ConversationParticipant` | 会话中的角色成员区间 | `conversation_participants` |
| `Message` | 按 `message_sequence` 排序的消息事实 | `messages` |
| `InputBatch` | 安静窗口关闭后的一段连续玩家输入 | `input_batches` |
| `ConversationTask` | 一次逻辑回复任务；重试复用同一个 `task_id` | `conversation_tasks` |
| `AgentResult` | 某次 Agent 尝试的候选结果和审核状态 | `agent_results` |
| `Thought` | 批准角色回复中有内容的私有思考记录 | `thoughts`，由 Memory Repository 管理 |

`Message` 是消息历史的权威记录。玩家消息通过 `input_batch_id` 关联输入批次，角色消息通过 `result_id` 和 `bubble_index` 关联批准的 Agent 结果。一次结果可以投影出多条有序角色消息，当前 Stub 默认只有一条。

构造角色自己的近期对话上下文时，Runtime 按 `result_id` 读取已批准回复中存在的 Thought，并把它附在对应的历史角色消息上。Thought 不进入玩家可见的消息历史。

## 输入和输出

公开输入包括：

- `SubmitMessageCommand`：账号、会话、玩家文本、图片、客户端消息标识和客户端时间。
- `SyncMessagesQuery` 或 `ConversationSyncQuery`：按游标读取消息历史。
- Worker 领取的 `ConversationTask`：包含输入边界、上下文边界、状态版本、上下文版本和 Trace 标识。

Agent 调用使用 `AgentInvocation`。Conversation Runtime 先根据冻结任务构造 `ContextSnapshotV2`，再填写 `ConversationScope`、`InvocationIdentity`、工具白名单和 `ExecutionPolicy`。Agent 返回 `AgentRunResult`，成功分支必须包含 `CharacterMessageProposal`，也可以明确返回 `NO_PROPOSAL`。

模块输出包括：

- `MessageReceipt`：说明玩家消息是否被接受及其 `trace_id`。
- 批准后的角色 `Message`、对应的 `AgentResult`，以及有内容时产生的私有 `Thought`。
- 任务和输入批次的最终状态。
- 带 `next_cursor` 的 `MessageBatch`，以及面向客户端的安全 Trace 摘要。

## 主流程

### T1：接受消息

`ConversationIntakeService.submit_message` 在一个短写事务中完成：

1. 校验会话、参与者、消息幂等键和输入能力。
2. 为消息分配单调递增的 `message_sequence`。
3. 写入玩家 `Message`，并把它加入当前 `collecting` 的 `InputBatch`；没有可继续使用的批次时创建新批次。安静窗口秒数来自 `settings.toml` 的 `conversation.quiet_window_seconds`。
4. 写入 `message.accepted` Trace。

T1 不调用 Agent，也不创建回复任务。相同客户端消息标识只能对应一条玩家消息；相同标识携带不同内容时返回幂等冲突。

### T2：关闭输入并领取任务

`ConversationPreparationService` 在消息提交、Worker 唤醒或恢复流程中运行：

1. 关闭安静窗口已经结束的 `collecting` 批次，得到 `waiting` 批次。
2. 检查会话类型、会话状态、唯一活跃角色、世界状态和角色回复资格。
3. 没有可恢复任务时，把按顺序排列的等待批次绑定到一个新的 `ConversationTask`。
4. 冻结输入最大序号、上下文最大序号、世界状态版本、角色状态版本和 `context_version`。
5. 领取任务时增加 `attempt_count` 和 `lease_generation`，然后在事务外构造上下文并调用 Agent。

上下文最大序号至少覆盖输入最大序号。`ContextSnapshotBuilder` 只读取不超过这个边界的消息、摘要、记忆、角色资源和情境视图，因此 Agent 调用期间出现的新消息不会改变本次输入。

### Agent 执行

`ConversationExecutionService` 为任务建立租约心跳，构造一次 `AgentInvocation` 并运行 Agent。模型 I/O 不持有 SQLite 写事务。调用开始、路由、模型用量和结果状态通过公共 Trace 记录，具体 Provider 由 Model Gateway 处理。

### T3：审核和提交

`ConversationCommitService` 在一个短写事务中重新检查：

- 任务仍由当前 Worker 持有有效租约；
- Invocation、Agent、Agent 类型和任务目的相符；
- 会话、参与者、上下文版本和回复资格仍然有效；
- 当前任务没有已经批准的结果；
- Proposal 满足 Contract 和 Runtime 审核规则。

审核通过后，事务依次写入 `AgentResult` 决议、角色消息，以及有内容时的 Thought，再写入输入批次覆盖状态和任务完成状态。任何一项失败都会让事务整体回滚。迟到结果、重复结果或来源版本过期的结果只记录 Trace，不改变已提交事实。

## 状态、重试和恢复

### 会话和输入批次

| 对象 | 状态 | 含义 |
|---|---|---|
| `Conversation` | `active` / `archived` | 归档会话不能创建新的角色回复任务 |
| `InputBatch` | `collecting` | 仍在安静窗口内接收连续玩家消息 |
| `InputBatch` | `waiting` | 已封口，等待绑定任务 |
| `InputBatch` | `assigned` | 已绑定一个任务，消息范围已经冻结 |
| `InputBatch` | `covered` | 任务已经产生最终处理结果 |
| `InputBatch` | `terminal_failed` | 任务达到最大尝试次数仍失败 |

### 回复任务和 Agent 结果

`ConversationTask` 依次使用 `pending`、`processing`、`retry_wait`、`deferred`、`completed` 或 `failed`。Provider 暂时错误、非法提案和审核拒绝可以进入 `retry_wait`；回复资格暂时失效会进入 `deferred`，资格恢复后由 T2 重新领取。租约过期由生命周期恢复逻辑重新安排。

`AgentResult` 只能从 `pending` 决定一次，终态为 `approved`、`rejected` 或 `expired`。`approved` 只表示候选结果通过审核，角色消息仍由 T3 在同一事务中生成。

当前代码在任务达到最大尝试次数后把输入批次置为 `terminal_failed`。这个状态没有自动重新打开同一来源的公共入口；如果产品需要再次执行，需要新增明确的运维或用户触发流程，不能把终态批次当作普通 `waiting` 批次重复领取。

### 恢复不变量

- Worker 只处理自己成功领取且租约仍有效的任务。
- `attempt_count` 和 `lease_generation` 同时参与提交前检查，旧 Worker 的结果不能覆盖新尝试。
- 任务结果、角色消息和输入批次覆盖状态在一个事务中提交，避免只写出半条回复。
- 重启时 `RuntimeLifecycle` 恢复过期的会话任务和相关反思任务；内存中的 Worker 状态不作为事实来源。

## Trace 和日志

Trace outbox 至少覆盖消息接受、输入批次封口、任务阻塞或领取、Agent 开始和结束、租约恢复、结果审核、角色消息提交、任务重试和任务完成。Trace payload 只保留状态、版本、错误码、数量和关联标识；玩家原文、完整 Prompt、角色完整输出和密钥由各自存储或 Debug Capture 管理。

普通日志用于运行诊断和耗时统计。Trace 用于按 `trace_id`、任务、结果或消息回查事实表。两者都不能改变 Conversation 的事务顺序。

## 测试入口

- `server/tests/test_runtime_t1.py`：消息接受、幂等和输入批次。
- `server/tests/test_runtime_t2.py`：批次封口、资格检查、任务领取和上下文边界。
- `server/tests/test_runtime_t3.py`：租约、迟到结果、审核和原子提交。
- `server/tests/test_runtime_acceptance.py`：从提交消息到角色回复的组合路径。
- `server/tests/test_conversation_runtime.py`、`server/tests/test_conversation_sync.py`：运行与同步接口。
- `server/tests/test_task_dispatcher.py`、`server/tests/test_fault_injection.py`：任务恢复和故障路径。
