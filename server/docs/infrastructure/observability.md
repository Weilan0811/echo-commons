# 可观测基础设施

## 三个部件

| 部件 | 保存内容 | 是否影响业务结果 |
|---|---|---|
| 运行日志 | 服务启动、Worker、错误和耗时等结构化 JSON Lines | 否 |
| SQLite Trace | Agent、任务、图、节点、审核和事实提交的安全摘要 | 否；通过 outbox 与业务事务关联 |
| Debug Capture | 本地开发时的完整模型请求、响应和 Harness 过程 | 否；默认关闭 |

三者都通过可选端口接入。业务流程不依赖日志文件或 Debug Capture 是否存在。

## Trace

`TraceRepository` 先将白名单 payload 写入 `trace_outbox`，再由 `TraceDeliveryService` 物化到 `traces`。Trace 通过 `trace_id`、`correlation_id`、`entity_type` 和 `entity_id` 关联运行对象。

当前覆盖：

- 消息接收和 InputBatch；
- ConversationTask 领取、执行、审核、完成和失败；
- GraphRun 创建、失败、审核和完成；
- NodeTask 领取、重试和失败；
- Agent step、模型用量和工具调用摘要；
- 事实提交结果。

`safe_trace_payload` 为每种事件登记允许字段。Trace 不保存玩家原文、角色完整输出、Prompt、密钥或内部路径。

## 查询

`TraceQueryService` 支持按 `correlation_id` 和业务实体查询。`ReflectionRunViewService` 在一个只读事务中关联：

```text
GraphRun → NodeTask → Artifact → GraphResult → 事实表
       └──────────────────────────────→ Trace
```

内部接口 `GET /internal/reflection/runs/{graph_run_id}` 返回该诊断视图，供本地工作台使用。

## Debug Capture

`AgentDebugCapture` 位于 `observability/debug_capture.py`，由 `server/config/settings.toml` 的 `observability.debug_capture_enabled` 显式启用，默认关闭；生产环境不创建。它写入本地忽略目录，不进入 SQLite Trace、普通日志或公共 API。调用位置在 Harness 和 Model Gateway，并用显眼的 `DEBUG CAPTURE` 注释标出。

## 测试入口

- Trace outbox 和安全字段：`server/tests/test_trace_outbox.py`、`test_observability_trace.py`。
- 日志和 Debug Capture：`server/tests/test_observability_logging.py`、`test_debug_capture.py`。
- 图诊断视图：`server/tests/test_reflection_run_view.py`。
