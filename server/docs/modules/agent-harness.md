# Agent 执行循环

实现位于 `agents/`。AgentInvocation 冻结 scope、明确类型的输入、输出契约、能力、预算和执行策略。ContextSnapshot 与 ReflectionNodeInput 是不同任务的具体输入；InvocationInput 只保存共同元数据。

CharacterAgent 由 CharacterRegistry 根据实例与模板构造。HarnessBackend 组装 AgentLoop；InputProjector 负责将正式输入转换为模型提示，OutputRegistry 注册具体输出解析器。执行循环调用真实模型，处理工具请求、工具观察和终态产物。

模型看见的工具定义与执行授权使用同一能力集合。MemorySearchTool 通过正式检索服务返回属于当前角色的可见材料。执行步骤、模型请求、工具调用和期限各有明确预算；重试通过失败分类与 RecoveryAction 表达，不改变持久任务原快照。

AgentRunResult 保存真实状态、产物、用量和失败信息。Agent 层不领取持久队列、不写入业务事实；队列、租约与事实审核归相应任务模块及 execution。输出契约为 character_message.v1 与 reflection_node.v1。

共享执行机制见 [持久任务](../infrastructure/durable-task-runtime.md)，真实网络请求见 [模型网关](model-gateway.md)。
