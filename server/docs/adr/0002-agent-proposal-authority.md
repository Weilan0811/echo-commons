# ADR-0002：Agent 提案权与 Runtime 提交权分离

> 状态：Accepted  
> 日期：2026-08-31

## 背景

角色语言和部分行为选择需要概率模型，但游戏状态、顺序、预算、合法性和恢复必须确定、可测试、可审计。若 Agent 直接调用 Repository 或修改权威状态，模型错误会绕过游戏规则并产生不可重放的状态变化。

## 决策

1. Agent 接收不可变上下文快照，只返回结构化 Proposal。
2. Agent 不获取数据库、Repository 或 Runtime 写入工具。
3. Runtime 使用同步、确定性的 Reviewer 审核 Proposal。
4. Proposal 先进入 pending，再由 Runtime 决定 approved、rejected 或 expired。
5. 只有 approved Proposal 可以在 T3 事务中产生权威消息和状态变化。
6. Agent 不分配消息 ID、服务端顺序、时间戳或状态版本。

## 结果

正面影响：

- 模型输出不会直接成为游戏事实；
- 审核、幂等、重试和持久化边界可独立测试；
- Stub、不同模型供应商和未来 Agent 实现可以替换；
- Safety、预算和动作合法性可作为审核链扩展。

代价：

- Agent Schema 与 Runtime Reviewer 必须保持版本兼容；
- 每种新动作都需要确定性验证和提交实现；
- 需要额外保存 Proposal 与 Decision，链路比直接生成回复更长。

## 重新评估条件

Agent 可以获得更多只读工具或提交更多 Proposal 类型，但不得因此获得直接写入权威状态的能力。若确需改变这一边界，必须由新的 ADR 取代本文。

