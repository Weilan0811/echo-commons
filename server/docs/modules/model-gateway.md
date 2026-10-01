# Model Gateway 模块

## 职责和边界

Model Gateway 是所有 LLM 请求的 Provider 边界。它把 Harness 的一次模型步骤转换成 Provider 请求，再把 Provider 响应归一化为固定的 `ModelResponse`。它隔离 SDK、认证、endpoint、请求参数、供应商错误分类、单请求重试和用量统计。

Gateway 不知道 Conversation、Reflection、Proposal 审核或 SQLite 事实。它不能读取 Repository，不能决定任务是否完成，也不能把模型响应直接写成游戏事实。

## 核心 Contract

| 对象 | 作用 |
|---|---|
| `ModelRequest` | 一次模型请求，包含 Invocation、Trace、Agent、步骤、消息和输出 Contract |
| `PromptMessage` | Provider 无关的角色消息和受限元数据 |
| `ToolCall` | Provider 归一化后的工具调用 |
| `ModelResponse` | 一次 Provider 响应的统一结果 |
| `ModelGatewayError` | 脱敏后的稳定错误和是否可重试标记 |
| `ModelEntry` | 一个模型、endpoint、凭据引用和请求参数 |
| `ModelRegistry` | 逻辑档位、任务路由、模型条目和本地凭据索引 |

`ModelResponse.kind` 当前有 `terminal`、`tool_call`、`no_proposal` 和 `invalid`。Gateway 只描述模型这一轮返回的形状；Harness 决定是否继续工具循环，最终由 Agent Contract 生成 `AgentRunResult`。

## 请求和响应边界

`ModelRequest` 的关键边界包括：

- `invocation_id`、`trace_id`、`agent_id`：关联一次 Agent 调用；
- `model_profile` 和可选 `model_entry_id`：选择逻辑档位或明确条目；
- `attempt`、`step_index`、`deadline_utc`：限制本次步骤；
- `messages`：Harness 已经排好顺序的 Prompt 消息；
- `output_contract`：模型必须满足的结构化输出目标；
- `allowed_tools`、`tool_definitions` 和 `remaining_tool_calls`：本步骤的工具范围；
- `max_output_tokens`、`temperature`、`top_p` 和 `stream`：请求级参数。

旧的紧凑 schema 字段目前只在边界做一次规范化，内部以 `OutputContractRef` 为准。Provider 返回后，Gateway 归一化模型名、请求标识、结束原因、首字节时间、总耗时、工具调用和 `UsageSummary`。

## 路由和配置

业务代码请求 `light`、`strong` 等逻辑档位，并可以按任务类型配置默认档位。`TaskRouting` 先决定请求档位；`ModelRegistry.resolve` 再找到具体 `ModelEntry`。当 strong 路由被禁用时，确定性地回退到 light，并把 `fallback_reason` 留在路由结果中。

配置来源：

- `server/config/model-registry.toml`：运行后端、档位、模型条目和请求默认值；
- `server/config/settings.toml`：按对话和反思用途设置请求级生成参数；未填写时使用模型条目默认值；
- 本地忽略的 secrets 文件：凭据值；
- `ModelEntry`：base URL、模型名、超时、Provider 重试次数、退避时间、输出长度和响应格式。

没有可用凭据时，真实 Provider 路径报告 `provider_not_configured`。离线测试显式使用 `FakeModelGateway`，它只按脚本返回结果，不模拟网络行为。

## Provider 执行

当前真实适配使用 OpenAI SDK 兼容的 `chat.completions` 入口：

```text
Harness ModelRequest
  → ModelRegistry.resolve
  → OpenAICompatibleGateway
  → Provider SDK
  → normalize response / usage
  → ModelResponse
```

`OpenAICompatibleGateway` 在 Provider 调用期间负责单请求超时、有限 Provider 重试、指数退避和流式响应聚合。它把不同 Provider 的 usage 字段统一为输入、缓存读取、缓存写入、输出和总量。Provider 重试属于一次 `ModelRequest` 内部行为，不增加 Agent 的逻辑 `step_index`，也不修改 Harness 消息历史。

## 错误和重试

Provider 错误被转换为稳定类别：

| 错误码 | 默认处理 |
|---|---|
| `timeout` | 可重试 |
| `rate_limited` | 可重试，可使用 Provider 的 `retry-after` |
| `temporary_unavailable` | 可重试 |
| `authentication` | 不可重试 |
| `quota_exceeded` | 不可重试 |
| `invalid_request` | 不可重试 |
| `invalid_provider_response` | 不可重试 |
| `provider_not_configured` | 不可重试 |
| `model_configuration_invalid` | 不可重试 |
| `unknown` | 当前按不可重试处理 |

Gateway 只对可重试的供应商错误按 `ModelEntry` 的次数和退避设置再次请求，并遵守本次请求的截止时间。下一次等待时间超过当前请求剩余时间时，Gateway 不再等待，保留原错误码和 `retry_after_seconds` 交给上层；请求开始前已经超过截止时间时返回 `timeout`。次数用尽后，`ModelGatewayError` 将具体错误码、`retryable` 和已有的 `retry_after_seconds` 交给 Harness。认证、额度和请求配置错误直接返回；输出格式修正与工具调用规则由 [Agent Harness](agent-harness.md) 负责。Provider 请求重试、Harness 内修正和持久任务再次执行分别计数。

Provider 响应也带有稳定的 `error_code`。`invalid_provider_response` 表示响应外层结构损坏，`invalid_model_output` 表示模型返回的 JSON 或工具参数无法解析，`output_truncated` 表示输出因长度限制被截断，`provider_refusal` 表示 Provider 拒绝生成。响应错误不会在 Gateway 内重新请求，由 Harness 根据错误码决定后续处理。

## Prompt 顺序、用量和调试

Prompt 的消息顺序由 Harness 负责。为了提高缓存命中率，稳定的 Identity、工具定义和输出 Contract 放在前面，快照状态、来源材料和具体任务放在后面；Gateway 只序列化，不重新排序或改写内容。

公共 Trace 和日志记录 Provider、模型、路由、步骤、耗时、用量、缓存命中比例、响应形状和错误码。完整 Prompt、原始 Provider 响应和异常对象只在显式启用的 `AgentDebugCapture` 中保存。Debug Capture 失败不能中断 Agent 执行。

`ProviderUsageTracker` 是进程内统计器，用于观测 Provider 总请求数和缓存命中率，不是账务数据，也不替代任务或事实表。

## 测试入口

- `server/tests/test_model_gateway.py`：请求映射、响应归一化、错误分类、超时和重试。
- `server/tests/test_model_gateway_recovery.py`：配置错误、Provider 重试、截止时间和响应错误码。
- `server/tests/test_agent_harness.py`：Gateway 与 Agent Step、工具循环和输出 Contract 的组合。
- `server/tests/test_agent_routing.py`：任务到逻辑模型档位的路由。
- `server/tests/test_debug_capture.py`：调试捕获开关和故障隔离。
