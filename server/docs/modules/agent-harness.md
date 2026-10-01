# Agent Harness 模块

> 状态：已实现

## 职责与边界

`agents/harness/` 在一次 `AgentInvocation` 内组织模型请求、只读工具、输出校验和运行结果。Runtime 提供不可变上下文、工具权限、预算和截止时间；Harness 返回 `AgentRunResult`，不读取 Repository，也不提交游戏事实。Provider 请求内的重试见 [Model Gateway](model-gateway.md)；持久任务的再次执行见[持久任务运行时](../infrastructure/durable-task-runtime.md)。

## Prompt 分层

Conversation 的 Prompt 分成公共规则和角色资料两组。`response_contract`、`conversation_guidance` 和 `agent_contract` 对所有角色共用；`character_profile`、`character_relational_dynamics` 和 `character_voice` 分别承载当前角色的档案、关系倾向和语言风格。核心记忆、状态、关系和摘要属于运行时上下文，也各自使用独立区块。Conversation 将这些内容组织成一段有明确分段的 system context，再接历史消息和当前输入；历史消息后不再插入状态或关系 system message。Reflection 使用公共 Contract、Agent Contract、角色档案和关系倾向，不加载 `conversation_guidance` 或角色语气。

Reflection 节点使用 Agent Contract、角色身份和关系语义，以及 `prompt.py` 生成的节点职责、来源和字段要求；它不加载聊天语气资源，避免把角色的说话风格带进摘要和关系判断。

## 运行状态

`AgentRunState` 保存本次运行的步骤、提示上下文、输出和用量，并包含一个 `HarnessControlState`：

- `disabled_tools`：本次运行已经停用的工具；
- `tool_progress`：按工具名保存 `ToolProgressState`，记录已见的进展键和连续无进展次数；
- `repair_counts`：按错误码记录同一次运行内的修正次数。

控制状态只属于一个 `AgentRunState`，不单独注册。工具进展也只在本次运行内计算，不写入业务状态。

`ToolRegistry` 保存 `ToolRegistration`。注册项包含工具、可选的进展提取器和无进展上限。新增工具只需要提供自己的注册项和进展提取器，Harness 不按工具名称写分支。

## 连续工具调用

一次运行可以依次执行“模型请求 → 工具结果 → 下一次模型请求”，直到获得合格输出、模型明确不提案，或达到停止条件。`ExecutionPolicy` 设置工具权限和请求预算；`HarnessPolicy` 设置单次运行的模型步数、模型请求、工具调用、修正次数和无进展上限。Reflection 节点默认允许两次模型步骤和请求，第二次请求用于修正第一次的结构化输出错误。模型一次请求返回多个工具调用时，Harness 按顺序检查权限和剩余预算，并记录每个结果。

当前会话注册的 `memory_search` 使用 `sourceId + contentVersion` 作为进展键。新来源会清零连续无进展次数；空结果和已经见过的来源会增加次数。第一次无进展时提示模型改变查询或直接回答；达到工具注册的上限后停用该工具，模型继续使用已有材料生成结果。重复调用本身不会直接失败。

## 错误修正和任务恢复

Harness 根据稳定错误码选择同一次运行内修正、任务重试或失败：

| 情况 | Harness 处理 | Runtime 处理 |
|---|---|---|
| JSON、字段或输出被截断 | 添加错误码和格式提示，再请求模型一次 | 修正成功后继续当前任务 |
| 工具参数无效 | 把工具错误结果交回模型修改 | 修正成功后继续当前任务 |
| Provider 暂时失败、工具暂时失败或来源版本变化 | 返回 `RETRYABLE` 和 `FailureInfo` | 按任务重试次数重新执行 |
| 工具未授权、配置错误或预算耗尽 | 返回 `FAILED` 和错误码 | 立即结束任务并记录批次失败 |
| 截止时间到达 | 返回 `RETRYABLE` 和截止时间错误码 | 按任务重试次数重新执行 |

一次错误码的修正次数受 `HarnessPolicy.max_repairs_per_error` 限制。修正提示只包含错误码、字段和格式要求，不加入新的业务事实。Runtime 使用 `decide_agent_run` 读取 `FailureInfo`，不会把所有 Harness 失败都当作同一种任务重试。

## 结果与观察

`AgentStep` 保存每次模型响应、工具活动、错误码和用量；`AgentRunResult` 保存最终状态、诊断码、修正次数和恢复信息。Trace 记录 step、工具结果、进展数量、连续无进展次数、运行停止原因和任务恢复结果。完整 Prompt 与模型原文只进入显式启用的 Debug Capture，工具结果也不能通过 Trace 成为业务事实。

## 验证

- `tests/test_agent_harness.py`：基础 Contract、权限、预算和截止时间；
- `tests/test_harness_tool_loop.py`：连续工具调用、多工具结果、来源进展、无进展停用、参数修正和输出修正；
- `tests/test_model_gateway_recovery.py`：Gateway 错误和同一次运行内输出修正；
- `tests/test_runtime_t3.py`：Conversation Runtime 根据恢复动作安排任务重试或立即失败。
