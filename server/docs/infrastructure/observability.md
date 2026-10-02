# 日志、追踪与内部诊断

infrastructure/observability 保存普通日志、AgentDebugCapture、TraceDelivery 与追踪查询。业务事务写入 trace_outbox，独立后台执行器投递到 traces；投递失败和重试不撤销业务事实。

普通日志记录事件、范围标识、任务状态、请求用量与耗时，不写入私有正文或凭据。完整模型捕获通过 debug_capture_enabled 显式启用，存放于配置指定的独立目录。

内部诊断读取持久化的对话快照和反思图。角色与社群归属在读取服务中验证；清除的 Thought 文字不会再次返回。追踪查询同时显示已投递和待投递事件及投递状态，保持真实来源链。

公开消息与轮次使用独立响应类型。/health/live 查询存活，/health/ready 查询已初始化数据库和实际后台执行状态，不发送额外模型请求。详细入口见 [服务说明](../../README.md)。
