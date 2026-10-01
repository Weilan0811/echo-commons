# ADR-0003：Agent 框架边界、Harness Loop Owner 与 Echo 可扩展 Agent 内核

> 状态：Accepted
> 日期：2026-09-03
> 后续决策：M0 兼容假设已由 [0004](0004-remove-m0-agent-compatibility.md) 取代；当前正式入口和 Proposal 持久化以 0004 为准。
> 相关模块：[Agent Contract 与模型运行时](../infrastructure/agent-runtime.md)、[Model Gateway](../modules/model-gateway.md)
> 相关决策：[0001 本地 SQLite Runtime](0001-local-sqlite-runtime.md)、[0002 Agent 提案权](0002-agent-proposal-authority.md)

## 1. 背景

Echo 后续可能包含多个 Character Agent、Narrative Agent、长期记忆、行动、事件卡、话题卡、主动性循环和每日批处理。通用 Agent 框架可以提供模型调用、工具、结构化输出、Graph 编排、Memory 和 Checkpoint，但通常也会带入自己的状态、持久化和 Agent 间协作语义。

Echo 的核心不变量不同于一般聊天 Agent：

- SQLite 和 Runtime 是游戏事实的权威来源；
- Agent 只能提交结构化 Proposal；
- 所有行动、消息顺序、卡牌变化、阶段变化和关系变化必须经过确定性审核和事务；
- 进程内事件只负责唤醒，不能成为持久化事实；
- Unity 只能消费公开的已批准结果。

因此需要决定：哪些能力采用现有框架，哪些能力由 Echo 自己设计。

## 2. 决策

本 ADR 采用分层混合方案：

1. **Echo 自己拥有 Agent Run 契约和权威边界**：`AgentInvocation`、`AgentStep`、`AgentRunResult`、`ProposalEnvelope`、AgentCatalog、能力白名单、Proposal 审核、Action/Memory/Card/Event 领域模型、Runtime 调度和 SQLite 持久化由 Echo 自己拥有。
2. **框架只进入 Harness/Provider Adapter**：现有框架可以实现一次完整 Harness Run，包括模型调用、结构化输出、类型化工具和内部 Agent Loop，但不能拥有 Echo 的权威状态或提交权。
3. **Echo-native 是 Harness 的唯一执行循环**：Runtime、Harness 和 Model Gateway 只保留一条可观测的模型调用路径。
4. **Model Gateway 由 Echo 自己定义**：所有 Provider/框架调用必须经过 Echo Gateway，以统一 Provider 切换、预算、deadline、错误、Trace 和安全字段。
5. **反思图由 Echo Runtime 自己管理**：使用固定图模板、持久节点任务、Artifact 和统一执行器组织反思；LangGraph 等 Graph 框架不作为总 Runtime，也不在当前反思模块中引入。其 Graph State、Checkpoint 和 Store 不能取代 Echo Domain State。
6. **Temporal 等持久化工作流平台暂不引入**：只有当每日批处理、长期离线回归或多进程调度超出当前 SQLite Worker 能力，并完成部署模型评估后，才单独立项。

## 3. 目标结构

```text
Echo Runtime / Domain / Store（自研、权威）
├─ Event & Signal Runtime
├─ Topic / Event Card Runtime
├─ Memory Service and Views
├─ Action Registry and Preconditions
├─ Agent Arbitration
├─ Proposal Review and Commit
└─ SQLite / Trace / Replay
        │
        ▼
Agent Protocol / AgentCatalog（自研、内部契约）
        │
        ▼
Character/Narrative Harness（Agent Loop Owner）
        │
        └─ Echo Model Gateway（自研端口）
                │
                ▼
        Provider SDK / Model Service
```

## 4. 采用现有框架的范围

可以采用的能力：

- Provider 请求适配；
- 结构化输出 Schema 生成与校验辅助；
- 类型化依赖注入；
- 完整的模型—只读工具—Observation 循环；
- Agent 内部的有限分支或子流程；
- 模型用量的底层读取。

不能交给框架的能力：

- 世界事实和阶段/关系状态；
- Proposal 是否批准；
- 消息 ID、顺序和权威时间；
- Action 的执行和前置条件；
- 事件卡/话题卡的生命周期；
- Echo 的长期记忆事实和主观关系理解；
- 多 Agent 的最终仲裁；
- Unity 公共响应的定义。

外部框架与 Echo Harness 只能有一个 Loop Owner：要么 Adapter 委托框架驱动完整内部循环，要么 Echo 使用框架的低层能力自行驱动循环。不得两者各自再包一层不可观测的 Agent Loop。

## 5. 备选方案

### 5.1 全盘采用完整 Agent 框架

优点：初期开发速度快，工具、Memory、Graph 和多 Agent 示例较多。

缺点：容易形成第二套状态机和持久化事实；框架的 Thread/Session/Memory/Checkpoint 语义未必符合 Echo 的阶段、卡牌、关系和恢复规则；将来替换框架的成本高。

结论：不采用为核心架构。

### 5.2 全部从零自研

优点：边界完全可控，依赖少。

缺点：需要重复实现 Provider 适配、结构化输出、工具循环、取消、用量读取和模型兼容细节；会把工程精力从游戏领域规则转移到基础设施。

结论：不采用为全部层级的策略。

### 5.3 混合方案

优点：游戏事实、Proposal 和扩展能力由 Echo 控制，模型调用和结构化输出可以利用成熟实现；外部框架可替换，Stub/Fake 仍可用于离线测试。

缺点：需要维护清晰的 Adapter 边界和重复映射；部分框架高级功能不能直接使用。

结论：采用本方案。

## 6. 代价与约束

- 需要维护 Agent Schema、Domain、Store 三套映射；这是为了保留权限和事务边界，不以减少代码为目标。
- 新 Agent 运行能力必须进入 Echo-native Harness，并通过 Model Gateway；不引入第二套 Agent Loop。
- 框架自身的 Trace、Memory 和持久化只能作为诊断或局部实现，不得默认写入 Echo 权威数据库。
- Agent 内部的非确定性只允许存在于模型调用和明确标记的工具活动；Runtime、反思图拓扑、审核、卡牌状态和提交流程必须保持可测试和可重放。

## 7. 接受依据

本 ADR 已确认以下条件：

1. Agent Loop 的 Owner，以及 `AgentInvocation`、`AgentStep`、`AgentRunResult`、`ProposalEnvelope` 的边界；
2. Character/Narrative Agent 的能力矩阵；
3. Model Gateway 的 Provider、预算、deadline 和错误策略；
4. 外部框架 Adapter 不会让 Runtime/Store 依赖框架；
5. M0 Schema 和 Stub 兼容；
6. Echo-native Harness 满足可替换和离线测试要求。

## 8. 重新评估触发条件

出现以下情况时，应新增 ADR 或重新评估本决策：

- 服务从单进程本地运行转为多进程/远程部署；
- Agent Run 需要跨数小时或数日等待并可靠恢复；
- Agent 内部图状态成为产品可见或权威事实；
- 需要让外部框架直接管理持久化 Memory；
- Provider 能力差异迫使公共 Proposal Schema 改变；
- Unity 需要接收内部 Proposal 而不只是已批准结果。
