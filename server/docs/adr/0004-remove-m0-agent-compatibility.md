# ADR-0004：删除临时 M0 Agent 兼容层并统一 Proposal 边界

> 状态：Accepted
> 日期：2026-09-04
> 后续决策：Proposal 持久化清理见 [0008](0008-remove-legacy-m0-persistence.md)；本 ADR 的 Agent 边界和 Handler 决策仍然有效。
> 注意：本 ADR 第 2 节第 4 项关于 `agent_proposals` 作为当前 Proposal 写入表的过渡决策，已由 0008 的 `agent_results` canonical 持久化决策取代；这里保留原文作为历史决策记录。
> 相关模块：[Agent Contract 与模型运行时](../infrastructure/agent-runtime.md)、[Conversation](../modules/conversation.md)
> 相关决策：[0002 Agent 提案权](0002-agent-proposal-authority.md)、[0003 Agent 框架边界](0003-agent-framework-boundary.md)

## 1. 背景

M0 为验证会话闭环临时引入了 `AgentTurnRequest`、`AgentReplyProposal`、`propose_reply()` 和 `situation_proposals` 专用路径。M1 已经建立 `AgentInvocation`、`AgentRunResult`、`ProposalEnvelope` 和 Harness Loop；继续保留旧入口会让 Runtime 同时维护两套 Agent 语义，并把未来行动、话题卡和事件卡继续挤进角色回复分支。

## 2. 决策

1. 删除旧 M0 的 Agent Protocol、适配器和专用 Proposal。Runtime 只接受 `RunnableAgent.run(AgentInvocation) -> AgentRunResult`；M0 测试 Stub 直接实现该入口。
2. `ProposalEnvelope` 作为所有 Agent 共用的候选提案外层；`ProposalPayload` 在 contracts 中集中扩展，Runtime 通过 `ProposalRegistry` 按 `kind` 分派审核和提交 Handler。
3. `CharacterMessageProposal` 是当前首个具体载荷，不携带行动列表。新增行动、叙事、话题卡、事件卡或记忆 Proposal 时，新增自己的 payload、能力声明、Handler、持久化和测试。
4. 新增 `0002_agent_proposals.sql`，作为当前唯一 Proposal 写入表。迁移从历史 `situation_proposals` 回填可关联记录并标记 `source=legacy_m0`；旧 `0001` 文件和历史表不修改、不删除。历史回填没有 `invocation_id`，因此该列允许为空；新 Agent Run 写入始终带有 invocation id。
5. 当前会话 Turn 对 `completed` Run 仍要求一个 `character_message` Proposal；这是会话流程策略，不是 Envelope 或 Harness 的通用限制。`no_proposal` 明确完成 Turn，不伪造消息。

## 3. 结果

- Runtime、Store 和测试不再依赖 M0 类型名或兼容分支；
- Proposal 的审查和提交可以按 Handler 增量扩展，未来类型不需要修改会话 Runtime 的角色字段访问；
- `0001` 历史数据仍可审计，且通过 `0002` 进入统一 Proposal 查询边界；
- 旧的 Python Agent 调用接口不提供兼容承诺。M0 是内部测试阶段，不是对外稳定 API；
- 当前仍只有角色消息 Handler，真实 Provider、AgentCatalog、Memory、Safety 和卡牌领域规则另行实现。

## 4. 重新评估触发条件

- 需要向外部插件或已发布客户端承诺旧 Agent Python 接口；
- 历史 Proposal 需要可恢复为完整 Agent Run，要求补充 invocation 审计数据；
- 多 Proposal 原子提交、跨 Turn 恢复或远程工作流改变当前 Handler/Runtime 事务边界。
