# 角色状态与玩家关系模块

## 职责和边界

该模块保存角色自身的叙事状态、角色与目标之间的有向关系、关系证据和有来源的态度摘要。状态变化和关系数值变化先由纯 Domain 规则计算，再由 Runtime 在审核后的事实提交事务中写入。

这里的“角色状态”有两种不同语义，必须分开：

- `CharacterState` 位于 Conversation 的回复资格边界，表示 `available`、`offline`、`busy` 等当前可回复状态。
- `CharacterStateEntry` 位于本模块，表示 `physical`、`mood`、`activity` 等有来源的叙事状态历史。

前者决定能否创建或继续角色回复任务，后者进入 Agent 上下文并参与 Reflection。它们使用不同的对象、版本和更新规则。

## 核心对象和持久化

| 对象 | 作用 | 主要表 |
|---|---|---|
| `CharacterStateEntry` | 一个状态类别的一条历史值 | `character_state_entries` |
| `RelationshipKey` | 账号、观察角色、目标类型和目标标识组成的有向关系身份 | 关系表主键 |
| `RelationshipEvidence` | 一条客观、可引用的关系事实 | `relation_evidence` |
| `RelationshipImpact` | 该事实对某个关系维度的离散方向和幅度 | 事务内值对象，不单独建表 |
| `RelationshipState` | 当前关系类型、数值、版本和态度摘要 | `relationship_state` |
| `RelationshipAttitude` | 引用证据的派生摘要 | `relationship_state` 的摘要字段 |

`RelationshipState` 只保存当前状态；历史事件由 `relation_evidence` 追加保存。`CharacterStateEntry` 按角色和状态类别追加版本，最高版本是当前值；旧值过期时不会自动恢复更早的值。

## 值域定义

| 对象 | 值 | 简单定义 |
|---|---|---|
| `relationship_type` | `stranger` / `acquaintance` / `friend` | 陌生人、熟人、朋友；陌生人没有 H/T/A 数值，后两类必须有完整数值 |
| H/T/A | `affection` / `trust` / `attachment` | 好感、信任、依恋；已初始化关系均为 0～100 |
| 关系影响方向 | `positive` / `negative` / `neutral` | 增加、减少、不变；等级分别为 1～3、1～3、0 |
| `state_kind` | `physical` / `mood` / `activity` | 身体状态、心境、当前活动；`value` 是有来源的文本，不是固定枚举 |

第一次有效互动后，关系初始化为熟人，并以 H=50、T=50、A=0 作为正常基准，再应用本次事件产生的关系影响；朋友需要 H≥60、T≥60 且有符合规则的证据。具体证据类别见下节。回复资格使用的 `available`、`offline`、`busy`、`story_absent`、`technical_error` 属于 Conversation 的 `CharacterState`，本模块只引用其边界。

## 状态输入和输出

输入来自已审核的 Reflection 候选和当前数据库版本：

- `StateEntryCandidate`：状态类别和值；过期规则由 Runtime 决定。
- `RelationshipImpactCandidate`：关系维度、正负方向、离散等级和来源引用。
- 当前 `CharacterStateEntry`、`RelationshipState` 和来源段版本。

输出包括新的 `CharacterStateEntry`、`RelationshipEvidence`、更新后的 `RelationshipState` 和版本冲突或来源错误。模型不能直接提交关系分数、状态版本、证据身份、发生时间或过期时间；这些字段由 Runtime 和 Domain 规则生成。

## RelationshipEvidenceKind

`evidence_kind` 是关系事实的有限业务类别。它供规则判断某条证据能否初始化关系、取得朋友资格或增加依恋，不承担来源类型、关系维度和情绪方向的职责。当前值为：

| 值 | 业务作用 |
|---|---|
| `interaction` | 一般有效互动；当前段反思事实处理器使用它初始化陌生关系 |
| `support` | 支持、帮助和积极承接；可参与朋友资格和依恋规则 |
| `conflict` | 冲突、伤害或明显分歧；可驱动负向关系变化 |
| `commitment` | 持续投入、承诺或共同承担；可参与朋友资格和依恋规则 |

`source_kind` 和 `source_ref` 说明事实从哪里来，`evidence_kind` 说明这件事在关系规则中属于哪一类。`RelationshipImpact.dimension` 说明影响 affection、trust 或 attachment，`direction` 和 `magnitude` 说明变化方向与离散幅度。四个字段不能互相替代。

当前 `segment_reflect` 的 `RelationshipFactHandler` 固定生成 `interaction`，并把模型返回的维度、方向和等级转换成一条 `RelationshipImpact`。支持、冲突和承诺类别已经由 Domain Policy 支持，具体生成规则需要对应的候选字段和 Runtime 处理器明确后才能启用。

## 纯规则

`apply_relationship_evidence` 只依赖传入的状态、证据、影响、策略、期望版本和当前时间：

1. 检查证据和当前有向关系属于同一 `RelationshipKey`。
2. 检查版本、时间、影响数量和每个维度最多一次。
3. 陌生关系只有遇到 `initializes_on` 中的证据类别才能初始化为 acquaintance。
4. 按关系类型、维度、等级和步长计算有限范围内的变化，结果限制在 0 到 100。
5. 只有符合资格类别并达到 affection、trust 阈值时，关系才会从 acquaintance 变为 friend。
6. 生成 `RelationshipTransition`，其中包含新状态、每个影响的前后值和状态是否改变。

`replace_character_state_entry` 对每个状态类别执行 compare-and-set（比较并设置）版本检查，生成下一个版本的条目。当前实现把 `activity` 的过期时间设置为记录时间后 24 小时，其他状态类别没有自动过期时间。

## Runtime 提交流程

Reflection Runtime 的事实提交顺序是：

1. 审核候选的来源引用、Graph Snapshot 版本、任务和 Proposal 状态。
2. 为关系候选生成稳定证据身份，并通过 `RelationshipEvidenceRepository.ensure` 做同来源幂等写入。
3. 读取当前关系状态，调用 `apply_relationship_evidence`，按版本保存变化。
4. 读取每个状态类别的最新条目，调用 `replace_character_state_entry`，追加下一个版本。
5. 与其它反思事实在同一个图级提交事务中完成；任何版本冲突都会让整个事务回滚。

关系证据和角色状态的来源引用指向 Reflection Graph 和候选指纹。它们不直接保存模型原文，也不绕过 `ReflectionGraphResult` 的审核状态。

## 持久化和失败

`character_state_entries` 是按类别追加的历史表，`relationship_state` 是按有向关系 compare-and-set 的当前表，`relation_evidence` 是追加且按来源去重的事实表。

以下情况拒绝本次事实：

- 状态或关系版本与数据库当前版本不一致；
- 关系目标、观察角色或证据身份不匹配；
- 证据来源为空、发生时间晚于记录时间或重复覆盖来源；
- 陌生关系收到不允许的分数、态度或依恋变化；
- 关系维度重复、等级超出 0 到 3 或方向与等级组合非法。

事务失败后不保留部分状态。下一次任务尝试必须重新读取当前状态，不能沿用失败尝试的旧对象。

## Trace 和日志

Trace 记录状态事实和关系事实的审核决定、提交数量、来源版本、状态版本和错误码。需要查看具体事实时，通过 `entry_id`、`evidence_id` 或 `RelationshipKey` 查询表；Trace 不保存模型原文、完整候选或私密态度正文。

## 测试入口

- `server/tests/test_state_relationship_domain.py`：状态和关系纯规则。
- `server/tests/test_state_repositories.py`：追加、compare-and-set 和来源去重。
- `server/tests/test_state_scenarios.py`：关系初始化、升级和状态过期场景。
- `server/tests/test_reflection_review.py`、`server/tests/test_reflection_persistence.py`：审核后事实提交。
