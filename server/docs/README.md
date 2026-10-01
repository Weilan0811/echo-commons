# 后端工程文档

`server/docs/` 记录后端当前实现。仓库根目录 `docs/` 负责产品、世界、角色、叙事、玩法和顶层系统设计；本目录负责代码结构、模块边界、持久化、验证状态和长期技术决策。

## 阅读顺序

1. [后端架构](architecture.md)：看系统组成和依赖方向。
2. [实现状态](implementation-status.md)：看当前能力、缺口和验证结果。
3. [应用组合](infrastructure/application-composition.md)：看 Runtime 模块如何组合。
4. [持久化与事务](infrastructure/persistence-and-transactions.md)：看数据库和事务边界。
5. [模块索引](modules/README.md)：进入 Conversation、Reflection、Memory、状态关系、Identity 和 Model Gateway。
6. [ADR 索引](adr/README.md)：查看长期决策。

## 文档权威范围

| 问题 | 权威文档 |
|---|---|
| 后端整体结构 | [architecture.md](architecture.md) |
| 当前完成度和限制 | [implementation-status.md](implementation-status.md) |
| 跨模块组合 | [infrastructure/application-composition.md](infrastructure/application-composition.md) |
| 数据库和事务 | [infrastructure/persistence-and-transactions.md](infrastructure/persistence-and-transactions.md) |
| 单模块行为 | [modules/](modules/README.md) 下的对应文档 |
| 长期架构决定 | [adr/](adr/README.md) 下的 ADR |

## 文档分层规则

后端文档按信息的稳定程度分层：

| 文档位置 | 记录内容 | 不记录内容 |
|---|---|---|
| `architecture.md` | 跨模块结构、依赖方向和系统边界 | 单模块的详细字段和阶段进度 |
| `modules/` | 模块职责、对象责任、输入输出、流程、状态、持久化、失败规则、Trace 和稳定契约 | 临时实施步骤和完整开发日志 |
| `implementation-status.md` | 当前完成度、已知缺口、验证结果和逐项开发路线 | 另一套模块设计或重复字段定义 |
| `design-drafts/` | 尚未进入正式文档的临时方案和实施拆解 | 已完成工作的长期说明 |
| `adr/` | 会影响长期边界的技术决策和不变量 | 普通开发进度和局部实现细节 |

模块文档可以记录已经确定但尚未实现的契约，必须明确标注状态。精确字段定义以代码 Contract、Domain 和 Store 为准；模块文档解释业务含义、责任和流程。每个事实只保留一个权威来源，其他文档通过链接引用。

设计草案用于尚未定稿的方案或当前实施拆解。方案确定或实施完成后，把稳定内容写回对应正式文档，并删除不再需要的草稿。已完成的实施历史不在正式文档中重复维护。
