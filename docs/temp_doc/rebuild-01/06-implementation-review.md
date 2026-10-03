# 文档重组前的源码复核与设计差异

日期：2026-10-02。状态：已完成一次重点复核，完整逐项认证仍待执行。配套：[重组方案](06-documentation-reorganization.md)、[信息清单](06-documentation-inventory.md)。

后续逐字核查确认原始提示存在实质改写，新增 D10，优先级 P0，列为待修改项目的最高优先级。完整范围、原文和比较证据见 [提示核查记录](07-prompt-preservation-audit.md)。下方测试结果及调用链检查不能证明提示内容保留。

原实现再次复核后的处理决定见 [status](../server/docs/status.md)。D03 的 partial 补充恢复归为继承的未实现能力；D04 不要求模型候选携带读取时版本，按原提交事务的版本规则核查；D07 的 interaction 消费边界在原实现中同样存在。下方保留初步复核记录，代码修复使用 status 中的最新裁定及 F01—F06 计划。

## 1. 方法、范围和证据边界

本轮对照根目录架构、任务 1 的保留规则、Git `a78c686^` 中的旧模块说明和当前源码，检查身份、消息、观察、快照、关系与状态、记忆消费者、反思五图、执行租约及既有测试断言。

重点沿“入口、准备、执行、审核、事实写入”检查实际消费者，尤其检查保留的算法是否真正进入模型任务。下面的“已查”只证明列出的路径和行为；信息清单全部条目的完整认证尚未完成。

本轮执行 `uv run pytest -m "not model" -q -o addopts=''`，结果为 **84 passed，9 deselected，34.02 秒**。这是正式 SQLite 与服务测试的当前结果。本轮没有调用真实模型、重新构建安装包或修改源码。此前真实模型和安装结果是历史证据，不能代替本轮新增差异的验证。

下方源码路径相对 `server/src/echo_commons/`，测试路径相对 `server/tests/infrastructure/`。上一轮文档修改仍在工作区，原代码提交为 `a78c686`，最终清理记录为 `8a799c9`。

## 2. 已检查调用链及判断

| 编号与信息条目 | 当前源码证据 | 本轮判断与后续 |
|---|---|---|
| R01，I04—I05 | characters/services/bootstrap.py；memory/services/bootstrap.py | 实例绑定模板版本，事务中创建状态与社群登记；初始记忆解析 self 为实际实例并建立索引。保留路径存在，资源全部字段和错误仍须按 I75 逐项核对 |
| R02，I09—I11 | conversations/services/intake.py；services/batching.py；repositories/messages.py | 幂等按玩家和客户端标识读取并比较会话、正文、可见性、提及、回复和私有接收者；重复返回位于新消息收集前。角色窗口强制为零 |
| R03，I13—I15 | social/planner.py、participation.py、domain.py | 同受众来源组合；一个运行轮次；独立角色任务；提及与最近发言排序。实际轮次无 pending 状态，属于 D06 文档契约差异 |
| R04，I19—I20 | perspective/policy.py；conversations/tasks/context.py；memory/services/retrieval.py、sealing.py | 观察检查范围、上限、成员区间与实际受众；归段和检索使用明确来源。当前读取路径有共同规则，所有消费者与重建仍需逐项认证 |
| R05，I21—I24 | conversations/tasks/context.py、execution.py；agents/contracts/context.py | 规划保存具体快照，执行读原快照；历史、resident 和 digest 有读取。自身历史 Thought 未进入快照，见 D01 |
| R06，I16—I17 | conversations/tasks/commit.py、lifecycle.py | 提交事务保存回应、Thought、零窗口批次和参与终态；受众使用原区间与当前成员交集；离开、归档和暂停有正式处理 |
| R07，I25、I30 | characters/domain/state.py；repositories/state.py；services/facts.py | 当前状态取最高已记录版本，过期不会恢复更早值；activity 写入设 24 小时有效期。缺少外部期望版本参数，见 D04 |
| R08，I26—I29 | characters/domain/relationship.py；services/facts.py；test_relationship_baseline.py | 关系公式保留初始化、资格、维度唯一、步长和边界比例。正式反思消费者固定 interaction，不能以领域中存在其他类别宣称正式图支持它们 |
| R09，I32—I35 | memory/services/sealing.py、batches.py、continuity.py | 精确消息及自身 Thought，数量字符限制；冻结摘要及前一 digest；写入检查前驱和覆盖。连续性 NoOp 偏差见 D02 |
| R10，I36—I37 | memory/services/organization.py、retrieval.py | 组织解析候选局部实体，页、边、消费与索引共用连接；检索过滤实际来源与版本。语义去重和陈述来源质量不能单凭此代码证明 |
| R11，I39—I42 | reflection/domain/graph.py；registry.py；coordinator.py；workflow.py | 五种固定拓扑存在，显式 workflow 只连接三种图；图和节点输入持久化。两种未接入图应保留完整已确认契约 |
| R12，I41、I43 | reflection/tasks/dependencies.py、queue.py、graph_commit.py | 等待前驱终态，绑定实际完成产物；可选失败可形成 partial，必需失败终止图。partial 新恢复运行入口未找到，见 D03 |
| R13，I44—I50 | reflection/tasks/review.py、graph_review.py、facts.py | 动作、身份、证据、类型、覆盖及候选检查存在；图级审核和所属事实写入分开。逐图 NoOp 规则缺乏区别，见 D02 |
| R14，I55—I60 | agents/contracts/invocation.py；agents/harness/policy.py、progress.py；conversations/tasks/prompt.py；reflection/tasks/prompt.py | 调用身份、动作空间及工具子集检查存在；预算和材料进展存在。完整错误分类、所有停止路径和提示语义仍需逐项认证 |
| R15，I61—I63 | execution/lease.py；reflection/tasks/readiness.py；reflection/tasks/queue.py；conversations/tasks/lifecycle.py | 心跳与执行并行，失去租约取消操作；反思实际请求前检查期限、尝试、范围、社群与可用状态。恢复图与恢复过期节点分别处理，见 D03 |
| R16，I64—I68 | reflection/tasks/graph_commit.py；app/lifecycle.py；infrastructure/database/connection.py | 图事实写入使用保存点，业务拒绝撤销事实并保留审核；应用启动恢复和退出关闭有实际入口。全部表语义、诊断响应字段及运行设置尚未完成逐项认证 |
| R17，I71—I84 | app/main.py；各模块 api；现有正式文档与检查工具 | 实际接口由代码登记，正式使用说明仍依赖根目录设计；配置、扩展和长期能力状态需要重组。链接检查只验证文件存在 |

以上判断没有把全部模块登记为“符合完整设计”。尤其 R05、R07、R09、R12、R13 存在差异或待裁定项目。

## 3. 差异清单

### D01：自身历史 Thought 的输入用途缺失

关联 I23。根目录 01 第 6.2 节允许自身 Thought 加入自身历史；旧 Conversation 说明明确按已批准结果取出 Thought 并附到对应自己的历史发言。任务 1 也要求保留私有 Thought 与独立来源能力。

当前 `ConversationContext.prepare` 读取消息、状态、关系、resident 和 digest，没有依赖或读取 ThoughtRepository。`ObservedMessage` 没有 Thought 字段，`MemoryContext` 也没有对应历史思考字段。提交保存 Thought，反思材料会读取 Thought，但对话准备路径不提供自身历史思考。

判断：已确认的用途在当前对话输入中缺少消费者。仅证明 Thought 已存储及可归段不足以证明用途保留。后续设计必须明确对应身份、历史边界、字符预算与清除行为，再通过真实消息和实际快照验证；本轮不修复。

### D02：连续性压缩允许已有批次以 NoOp 完成

关联 I44、I47—I48。旧 Reflection 的 continuity_compress 契约明确“已有冻结批次时不接受 no_op”。这与有真实摘要来源就应推进连续性覆盖的用途一致。

当前路径如下：

1. `ReflectionReview.check` 对模型节点普遍允许 `no_op`。
2. `GraphReview.check` 遇到 NO_OP 直接返回允许，绕过该图必须包含 digest 的检查。
3. `ReflectionFacts.apply` 在未找到 digest 时传递空内容。
4. `MemoryContinuity.compress` 在内容为空时直接返回。
5. `ReflectionGraphCommit.commit` 仍可保存 approved 并完成图。

判断：源码存在明确行为差异，冻结材料可以结束图而未生成 digest，覆盖没有推进。重新调度是否复用同一图还取决于批次身份，不能据此推断系统会自动补全。需要恢复逐图 NoOp 审核及相应失败验证，禁止将共同文档改成“一律允许”使差异消失。

### D03：partial 图的恢复运行尚无实际入口

关联 I43。旧 Reflection 设计要求：可选节点失败后保留 partial；后续恢复建立新运行，复用原快照和完成产物，只执行失败的可选节点。

当前图提交可以产生 partial。Coordinator 的相同来源查询返回已有图，Workflow 仅提供段及摘要调度，Queue 的 recover 处理过期执行节点。当前检查范围内没有建立 partial 恢复运行并复用已完成产物的服务。

判断：partial 保存与过期租约恢复已存在；已确认的恢复运行设计尚未找到消费者。需裁定该能力是否属于本次保留范围，正式状态应据实际入口标明，不能把队列 recover 当成恢复运行已经实现。

### D04：状态写入未表达调用方期望版本

关联 I25、I30。任务 1 要求保留状态历史、有效时间和期望版本检查。

当前 StateChange 只有 kind 和 value，CharacterFacts.apply 在事务内读取最大版本再追加。ReflectionSources 复核消息、Thought、摘要和 digest，没有将原快照的状态版本作为写入前提。

判断：已查路径没有保留调用方期望状态版本的表达。事务串行能保证版本递增，不能单独证明基于旧状态生成的候选仍适合覆盖新状态。两个有效反思来源可以分别生成状态候选，因此需要继续检查并发图的正式调用和设计政策。本轮将版本校验缺失登记为偏差；是否拒绝、重新分析或采用明确追加政策需要设计裁定和实际交错提交验证。

### D05：重复关系来源直接跳过，未比较变化内容

关联 I30。CharacterFacts.apply 找到同一个关系来源证据后直接 continue；状态来源重复则会比较 value，不同内容报告冲突。

判断：两个事实路径的重放比较不同。上层图与来源版本是否保证关系变化绝不出现不一致重放，尚未得到完整证明。列为待查，不把它直接宣称为当前已复现业务故障。验证需使用正式允许来源和调用链，检查相同及不同候选重放；不为不可达输入增加保护。

### D06：目标契约与实际对象已经不一致

关联 I04、I09、I15、I21。根目录设计列出 pending 轮次、包含系统主体的 ActorRef、统一 EventRef，以及自身意愿内容。实际 TurnStatus 只有 running/completed/cancelled；ActorKind 只有 player/character；shared 未找到 EventRef；SelfContext.intent 有默认空值，CharacterContext 没有填充意愿。

判断：存在设计与实现定义差异，但不一律判定缺少必要功能。轮次在同一规划事务直接建立可以合理省略持久 pending；系统事件与意愿需根据当前实际需求裁定。每项都必须保留原出处、理由与长期定义，不允许在搬文档时无记录消失。未来活动来源也不能仅凭 EventRef 名字存在就认为接入完成。

### D07：关系算法存在，正式消费者支持范围有限

关联 I27—I29。领域函数保留三维数值、初始化、朋友资格和依恋资格；当前反思事实固定创建 interaction 证据。朋友与依恋所需 support/commitment 不能仅凭领域枚举存在就进入正式生成链路。

判断：这是需要准确保留的实现边界，尚无证据表明它属于本轮引入的退化。正式设计解释完整算法及证据类别，状态文档分别列出消费者已经提供哪些类别，避免读者误认为所有资格路径都已接入。

### D08：长期文档无法独立使用

关联 I71—I84。当前 README 的 HTTP 契约，架构的完整活动流程，以及验收和实现状态均链接根目录重建资料。数据库参考完整列出结构，但很多字段业务意义、JSON 内容和生命周期需要读代码。上一轮补充没有展开全部五图契约。

判断：文档交付明确未完成。修复依据是信息清单与长期目标结构，不能以机械链接检查通过替代独立阅读验收。

## 4. 尚未证明的范围及后续验证

| 待查范围 | 必须得到的证据 |
|---|---|
| 旧规则和旧测试目标完整保留 | 对 task-01 的全部保留条目及旧测试分类逐项映射到当前调用链和实际断言，明确废弃与缺失 |
| 五图完整契约 | 对旧每张节点表、动作到候选、图特定规则和未实现步骤核对当前定义及消费者 |
| 状态与关系全部算法 | 检查默认步长、系数、初始化、资格、边界、版本及正式证据生成路径 |
| 所有上下文语义 | 核对模板规则、自身 Thought、来源陈述、状态关系、历史裁剪和每用途提示 |
| 每种失败与恢复 | 真实等待、重试、过期、暂停、partial 恢复、图拒绝和事务回滚；按实际支持路径验证 |
| HTTP、配置和资源契约 | 当前 OpenAPI、全部设置、资源格式与完整合法示例，检查每个字段及错误响应 |
| 数据库全部语义 | 逐表字段及 JSON 业务结构、关系、版本、消费、清除和所有实际写入消费者 |
| 模型端到端与安装 | 必要整改后再次运行真实模型及安装场景，保存实际路由及范围明确结果 |

84 项快速测试通过证明现有断言仍通过。D01—D04 的差异同时存在，因此不能再从测试数量或三种图正常运行推出“全部有效设计已保留”。本轮没有扩大验证结论，也没有用假模型或替身检查补足空白。

## 5. 整改归属与本轮边界

文档重组负责恢复完整有效设计、消除临时依赖并登记真实状态。源码偏差在独立后端整改任务中处理，必须先确定相关设计含义，再修复与验证。已确认未实现功能继续保持未实现，同时保存完整契约。

本轮只新增本组规划与复核文档，更新根目录索引。没有改动后端源码、用户数据、密钥、生产模型选择或上一轮未提交的正式文档修订。
