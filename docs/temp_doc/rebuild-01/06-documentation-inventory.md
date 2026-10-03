# 完整信息清单与长期归属

日期：2026-10-02。配套：[重组方案](06-documentation-reorganization.md)、[源码复核](06-implementation-review.md)。

本清单定义应当保留和解释的信息。目标路径相对拟重组后的 `server/docs/`。条目列出验收问题，写入标题或贴上源码路径不等于完成。此清单是初始完整范围，迁移时发现更细的有效规则继续登记在对应条目中。

## 1. 资料来源与迁移记录

| 来源 | 使用方法 |
|---|---|
| 根目录 01—05 | 提取用户确认的目标、规则、运行模型和验收要求，迁入长期设计或验证说明 |
| task-01-confirmation.md | 对照确认保留的算法、规则和原测试目标，防止重建丢失有效行为 |
| Git `a78c686^:server/docs/` | 恢复旧模块和基础设施说明，逐项过滤已经明确删除的产品耦合与旧接口 |
| 当前 server/docs 及 README | 保留准确内容，纠正缺失、重复、外部依赖与不准确实现声明 |
| 当前源码、SQL、资源、配置与 OpenAPI | 证明实际入口与行为，登记设计差异，生成机械参考 |
| 当前正式测试与真实运行记录 | 判断实际断言及执行范围，登记尚未得到证明的要求 |

每个条目的执行记录包括原出处及具体规则、长期目标章节、源码入口及调用链、验证场景及断言、差异、处理决定、验收状态。章节写完与代码符合分别记录，二者不能共用一个完成标记。

## 2. 系统、身份和交流

| 编号 | 必须完整解释的信息与验收问题 | 权威目标 |
|---|---|---|
| I01 | 平台目标、支持人类和多角色的范围；本地单进程假设及适用条件 | design/system.md |
| I02 | 系统对象关系、依赖方向、权威事实、提议和诊断的区别 | design/system.md |
| I03 | 从玩家输入到回应及从经历到长期事实的端到端顺序 | design/system.md |
| I04 | Community、Player、ActorRef、CharacterBlueprint、CharacterInstance 的身份和唯一性 | design/identity-and-communities.md |
| I05 | 模板版本绑定、独立初始化、自身引用解析、资源失败与重复创建 | design/identity-and-communities.md |
| I06 | 社群成员与会话成员分别决定什么，加入、离开和重新加入如何保留历史 | design/identity-and-communities.md |
| I07 | 世界时间、UTC、时区、game_day、运行期限和暂停的区别 | design/identity-and-communities.md |
| I08 | 直接会话与群聊的成员规则、归档、生命周期和正式入口 | design/conversation-and-social.md |
| I09 | 消息发送者、序号、回复对象、提及、可见性、实际受众与来源身份 | design/conversation-and-social.md |
| I10 | 客户端幂等范围、比较字段、重复请求、内容冲突及窗口不延长 | design/conversation-and-social.md |
| I11 | 玩家窗口、不同发送者与受众、交错消息、到期与角色零窗口 | design/conversation-and-social.md |
| I12 | 气泡展示与一次权威产物，角色批次因果来源及连续接话触发边界 | design/conversation-and-social.md |
| I13 | SocialTurn 的来源冻结、同受众组合、会话轮次串行与角色任务并发 | design/conversation-and-social.md |
| I14 | 参与资格、提及优先、轮换、人数限制、稳定顺序及全部沉默 | design/conversation-and-social.md |
| I15 | ParticipationDecision、任务与轮次状态，失败、沉默和取消如何共同完成 | design/conversation-and-social.md |
| I16 | 完整提议、长度、回复来源、原成员区间、迟到结果、重复提交和原子写入 | design/conversation-and-social.md |
| I17 | 公共与私有来源如何影响回应；受众离开再加入为什么不能获得旧回应 | design/conversation-and-social.md |

## 3. 观察、上下文、状态和关系

| 编号 | 必须完整解释的信息与验收问题 | 权威目标 |
|---|---|---|
| I18 | 客观世界、内部认识、角色记忆的含义及实际存储职责 | design/perspective-and-context.md |
| I19 | can_observe 的全部条件、原成员区间、历史上限和私有受众 | design/perspective-and-context.md |
| I20 | 消息列表、搜索、重建、归段及反思如何复用观察规则 | design/perspective-and-context.md |
| I21 | ContextSnapshot 五组信息、动作空间、来源版本、必需字段与实际内容 | design/perspective-and-context.md |
| I22 | 同轮次共享历史上限、独立快照、持久化、重启与重试保持原输入 | design/perspective-and-context.md |
| I23 | 历史裁剪、摘要覆盖重叠、常驻预算、自身历史发言与自身 Thought 用途 | design/perspective-and-context.md |
| I24 | ToolReadPolicy 的观察时间、来源版本及跨会话检索限制 | design/perspective-and-context.md |
| I25 | 可用状态与叙事状态；状态类别、初始值、版本、有效期、过期不恢复旧值 | design/character-state-and-relationships.md |
| I26 | 有向关系身份、玩家及角色目标、当前值与追加证据的职责 | design/character-state-and-relationships.md |
| I27 | 陌生、熟人、朋友；H/T/A 三维含义、值域、初始基准和资格证据 | design/character-state-and-relationships.md |
| I28 | 正负中性、等级、步长、关系类型系数、边界比例及计算例子 | design/character-state-and-relationships.md |
| I29 | interaction、support、conflict、commitment；朋友与依恋资格及当前消费者能力 | design/character-state-and-relationships.md |
| I30 | 状态与关系的版本冲突、来源重复、态度摘要、回滚和观察者隔离 | design/character-state-and-relationships.md |

## 4. 记忆与五种反思图

| 编号 | 必须完整解释的信息与验收问题 | 权威目标 |
|---|---|---|
| I31 | 初始记忆、resident、recallable、private、主体引用、有效期及模型读取 | design/memory.md |
| I32 | MemorySource 的类型、身份、版本、覆盖与 Thought 清除后来源保留 | design/memory.md |
| I33 | 精确归段、私有缺口、消息与自身 Thought、数量字符预算和重放 | design/memory.md |
| I34 | 段摘要写入、sealed/ingested、来源一致性与消费者独立进度 | design/memory.md |
| I35 | SummaryBatch 连续选择、冻结引用、未完成段、前一 digest 与材料预算 | design/memory.md |
| I36 | 长期页、实体、别名、边、规范化、局部引用、正式标识与消费事务 | design/memory.md |
| I37 | jieba、FTS5、候选排序、正式来源过滤、版本变化、重建及搜索无修改 | design/memory.md |
| I38 | 玩家陈述、自述、关系认识和共同经历证据的区别；不得补造具体历史 | design/memory.md |
| I39 | 五图各自用途、彼此关系、已实现/已确认未实现/未确定功能 | design/reflection/README.md |
| I40 | 图定义、运行、节点、快照、输入、产物、候选、Batch 与审核记录 | design/reflection/execution-model.md |
| I41 | 依赖模式、条件激活、前驱绑定、冻结输入、不可变产物和证据映射 | design/reflection/execution-model.md |
| I42 | 模型节点与代码聚合、行动到候选、节点提交与图级提交的完整过程 | design/reflection/execution-model.md |
| I43 | 图和节点完整状态机、必需与可选失败、partial、租约恢复与恢复运行 | design/reflection/execution-model.md |
| I44 | 图级审核、类型与来源、预算、NoOp、拒绝、事实保存和真实回滚 | design/reflection/execution-model.md |
| I45 | segment_reflect 的来源段、四节点拓扑、follow_up 条件、三类候选与消费者 | design/reflection/segment-reflect.md |
| I46 | segment_reflect 每节点输入字段、前驱、行动输出、证据和事实组合；完整例子 | design/reflection/segment-reflect.md |
| I47 | continuity_compress 的两节点拓扑、前一摘要、覆盖序号、来源连续和 NoOp 限制 | design/reflection/continuity-compress.md |
| I48 | continuity_compress 输入输出字段、摘要大小、过期前驱、重复消费和两批例子 | design/reflection/continuity-compress.md |
| I49 | memory_organize 双分支拓扑、各自材料、记忆页类别和实体边行动 | design/reflection/memory-organize.md |
| I50 | memory_organize 主体解析、别名复用、来源区别、候选审核、消费和完整例子 | design/reflection/memory-organize.md |
| I51 | diary_compose 游戏日与真实来源选择、空白日、两节点拓扑及日记行动 | design/reflection/diary-compose.md |
| I52 | diary_compose 唯一性、覆盖、Thought 保留清除、审核消费者和具体未接入步骤 | design/reflection/diary-compose.md |
| I53 | view_refresh 已提交事实、ChangeSet、代码规划、三个条件分支和聚合拓扑 | design/reflection/view-refresh.md |
| I54 | view_refresh 各视图字段、事实来源、核心记忆引用、版本重建与未接入步骤 | design/reflection/view-refresh.md |

I45—I54 每项同时包含触发、材料、预算、拓扑、节点、聚合、审核、事务、重复、失败和运行例子；表中突出内容不能替代这些共同要求。五图的 NoOp 许可分别定义，禁止在共同章节一句话决定全部图行为。

## 5. Agent、执行、存储和运行

| 编号 | 必须完整解释的信息与验收问题 | 权威目标 |
|---|---|---|
| I55 | 实例 Agent、调用身份及用途、具体输入类型、动作空间、输出契约和归属检查 | design/agents-and-models.md |
| I56 | 已实现、模板与任务能力交集；模型工具定义和实际授权如何一致 | design/agents-and-models.md |
| I57 | 提示分组、角色历史身份、对话与反思不同用途、输出 schema 与无提案 | design/agents-and-models.md |
| I58 | 工具循环、参数错误、进展键、连续无进展停用、格式修正及停止条件 | design/agents-and-models.md |
| I59 | 请求、步骤、工具、修正和期限预算；供应商、Harness、任务三级重试 | design/agents-and-models.md |
| I60 | 模型登记、light/strong 路由、SDK 转换、流式、错误、真实用量和客户端关闭 | design/agents-and-models.md |
| I61 | 独立队列与处理器、领取、owner/attempt/generation、到期及重复结果 | design/task-execution.md |
| I62 | 共享模型额度、等待时心跳、请求前复核、退出取消及工作状态 | design/task-execution.md |
| I63 | 暂停、恢复、归档、成员离开、重启、退避、终态失败及后续输入 | design/task-execution.md |
| I64 | 每个对象与表的关系、字段业务含义、JSON 内部结构、关键约束和读取边界 | design/persistence.md |
| I65 | 跨模块同一连接、短事务、保存点、业务拒绝与数据库失败的不同结果 | design/persistence.md |
| I66 | 初始结构、迁移登记、失败回滚、只读命令、备份与已有数据保留 | design/persistence.md |
| I67 | 日志、outbox、traces、捕获的用途、载荷、投递租约和重试 | design/observability.md |
| I68 | 上下文、反思和追踪诊断的范围与来源链，Thought 清除、公开响应与隐私 | design/observability.md |
| I69 | 活动对象、观察、合法动作、版本、结果来源、独立 ActivityTask 和提交 | design/activity-integration.md |
| I70 | 飞行棋完整并行流程、固定行动与随时聊天、过期操作、共享调度和未来验收 | design/activity-integration.md |

## 6. 参考、指南与长期状态

| 编号 | 必须完整解释的信息与验收问题 | 权威目标 |
|---|---|---|
| I71 | 全部公开 HTTP 方法路径、字段、响应、状态码、范围和真实请求示例 | reference/http-api.md |
| I72 | 内部及健康接口、游标字段及失效、错误协议、受众和响应过滤 | reference/http-api.md |
| I73 | Settings 全部设置、默认值、参数约束、预算关系、文件路径与 CORS | reference/configuration.md |
| I74 | 模型 TOML、供应商、生成参数、凭据引用与配置失败 | reference/configuration.md |
| I75 | manifest、身份、语气、关系倾向、能力、预置记忆格式和版本；完整合法示例 | reference/character-resources.md |
| I76 | 完整真实字段、主外键、唯一键、CHECK、索引、FTS 内部表边界 | reference/database-schema.md |
| I77 | 入口、类型、服务、存储、配置和测试的实际位置 | reference/source-map.md |
| I78 | 空库、示例、启动、多角色、私有交流、只读检查、导出和安装包 | guides/local-development.md |
| I79 | 前端创建顺序、选定身份、发送、轮询消息与轮次、错误及成员变化 | guides/frontend-integration.md |
| I80 | 故障阶段定位、真实配置问题、期限、租约、暂停、重启及残留进程 | guides/debugging-and-recovery.md |
| I81 | 增加模板、工具、反思节点、消费者、任务与活动的具体修改入口和验证 | guides/extending-the-platform.md |
| I82 | A01—A32 对应长期场景、当前断言、真实模型环境、安装步骤及限制 | guides/verification.md |
| I83 | 每项能力的设计、实现和验证状态，已知差异及未来消费者 | status.md |
| I84 | 每项架构决定的背景、约束、取舍、结果、适用条件与设计链接 | adr/ |

## 7. 迁移过程的完整性检查

先对照旧文档中的每个功能章节、规则表、公式、节点表与运行例子，再对照根目录确认规则和源码入口。不能只比较标题、行数或类名。

迁移后进行三个阅读检查：设计读者不看源码解释完整运行；前端读者按接入指南使用真实接口；维护者按开发说明定位与验证。最后验证所有永久信息在 server 内可达，临时资料只作为历史出处。

I01—I84 已写入长期目标位置，逐项入口及重建检查见 [本轮记录](06-reconstruction-result.md)。当前状态为文档已写入、待用户审核，代码一致性不能据此登记完成。源码证据与实际差异见复核记录及 server 的长期状态；用户审核后再执行代码整改及相应真实验证。
