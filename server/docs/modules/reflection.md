# Reflection 模块

> 本文档是后端 Reflection 模块的现行设计说明。它说明固定图的输入、节点输出、聚合结果、审核边界和事实消费者。
>
> 代码字段的精确定义以 [reflection.py](../../src/echo_server/agents/contracts/reflection.py)、[reflection_graph.py](../../src/echo_server/agents/contracts/reflection_graph.py) 和 [domain/reflection_graph.py](../../src/echo_server/domain/reflection_graph.py) 为准。本文档维护字段的业务含义和模块责任。
>
> 当前正式图名称使用 segment_reflect。segment_ingest 只存在于历史 migration 和旧文案中，不作为新图名称。

## 1. 模块职责

Reflection 模块把一组已经冻结的来源材料交给固定图执行。Runtime 负责创建图运行、冻结快照、领取节点、调用 Agent、保存 Artifact、激活后继节点、聚合提案、审核结果和提交事实。

Memory、状态关系和视图 Repository 保存事实或派生结果。Agent 只能返回节点动作，不能读取 Repository，也不能直接修改事实。

本文档包含两类内容：已实现的模块行为，以及已经确定但尚未接入 Runtime 的图契约。开发进度、验证顺序和工作台任务统一记录在 [implementation-status.md](../implementation-status.md)。

Reflection 当前只登记五种固定图：

| 图类型 | 业务用途 | 契约状态 |
|---|---|---|
| segment_reflect | 处理一个已封口消息段，生成段摘要、关系影响和角色状态 | 已实现的模块契约 |
| continuity_compress | 将连续的段摘要压缩为连续性摘要 | 已接入 Runtime |
| memory_organize | 从段摘要及其来源消息整理长期记忆和记忆图 | 已接入 Runtime |
| diary_compose | 从指定游戏日的角色材料生成私人日记 | 已确定契约，尚未接入 Runtime |
| view_refresh | 根据已提交事实刷新关系态度、状态摘要和核心记忆视图 | 已确定契约，尚未接入 Runtime |

图类型已经登记不代表该图已经能够从来源进入 Runtime 并完成提交。是否可运行以本文档的状态和 [implementation-status.md](../implementation-status.md) 为准。

## 2. 共同执行模型

### 2.1 图级流程

~~~mermaid
flowchart LR
    A[Graph trigger] --> B[ReflectionGraphRun + root NodeTask]
    B --> C[GraphContextSnapshot]
    C --> D[NodeInput projection]
    D --> E[AgentInvocation]
    E --> F[AgentRunResult]
    F --> G[ReflectionArtifact]
    G --> H[Successor NodeTask]
    H --> I[ReflectionBatch]
    I --> J[ProposalEnvelope]
    J --> K[ReflectionReviewer]
    K --> L[Graph-specific commit]
    L --> M[SQLite facts or derived views]
~~~

模型调用在 SQLite 写事务外执行。节点完成时，Runtime 在短事务中重新检查租约、图快照和输入指纹，再写入 Artifact、完成 NodeTask 并创建后继任务。所有需要提交的节点完成后，Runtime 从非聚合节点 Artifact 生成一个 ReflectionBatch，再生成唯一的 ProposalEnvelope(kind=reflection_batch)。

### 2.2 共享对象的责任

| 对象 | 责任 | 不负责的内容 |
|---|---|---|
| ReflectionGraphDefinition | 描述图类型、节点、依赖、输入 Contract、输出 Contract 和执行形状 | 不保存运行状态，不调用模型 |
| ReflectionGraphRun | 保存一次图运行的身份、来源范围、快照身份、拓扑版本、状态和执行代数 | 不保存每次模型调用的完整输入输出 |
| ReflectionNodeTask | 保存一个节点的依赖、状态、租约、attempt、输入指纹和 Artifact 引用 | 不决定事实是否写入 |
| GraphContextSnapshot | 保存一次图运行共享的不可变上下文和来源范围 | 不包含 task ID，不随节点重新生成 |
| NodeInput | 从快照投影出单个节点需要的上下文、前置 Artifact 和证据引用 | 不拥有独立事实版本 |
| ReflectionArtifact | 保存一次节点执行的不可变结构化输出、输出 Contract、输入指纹和来源引用 | 不直接写权威事实 |
| ReflectionCandidate | 表达经过 Runtime 归一化的可审核候选 | 不保存租约、调度字段或完整 Prompt |
| ReflectionBatch | 汇聚本次图的候选、Artifact 引用、证据和 no-op 结果 | 不表示审核已经通过 |
| ProposalEnvelope | 将图级 Batch 交给统一审核入口；图身份放在 origin | 不保存图运行状态或事实提交状态 |
| GraphReviewRecord | 保存图级审核结果和审核码 | 不替代事实表 |

对象之间的关系如下：

~~~text
NodeInput
  → AgentRunResult(ReflectionNodeOutput)
  → ReflectionArtifact
  → ReflectionCandidate(0..N)
  → ReflectionBatch
  → ProposalEnvelope
  → GraphReviewRecord + graph-specific fact commit
~~~

ReflectionBatchProposal 只保存 outcome、候选和 no-op 原因。graph_run_id 由 ProposalEnvelope.origin 保存，节点任务身份由 Artifact 引用表达，Proposal payload 不复制这些字段。

### 2.3 图级快照和节点输入

GraphContextSnapshot 由 Runtime 在同一只读边界构造，包含：

- account_id、character_id；
- IdentityContext；
- CharacterStateSnapshot；
- RelationshipStateSnapshot；
- MemoryContext；
- ReflectionWindowContext，包括消息序号范围；
- 有来源标签的 ReflectionSourceMaterial；
- CapabilityView；
- GraphSourceScope，每个来源包含 kind、ref、version。

NodeInputProjector 根据节点类型选择字段，并附带：

- snapshot_ref；
- node_key、node_kind；
- 输入和输出 Contract；
- 模型档位；
- 前置 Artifact 投影；
- EvidenceRef；
- node_input_fingerprint。

快照使用公共 `GraphSnapshotAssembler` 组装。`SegmentGraphSnapshotBuilder` 和 `MemoryOrganizationGraphSnapshotBuilder` 分别接收自己的任务 payload，负责准备不同来源单位的材料；其他图接入时沿用这个分工，不能把任务专用参数继续堆进公共构造器。

### 2.4 节点动作到候选的映射

模型输出是 ReflectionNodeAction 联合，Runtime 按节点类型检查动作，再由 ReflectionArtifactNormalizer 转为候选。

| 节点动作 | 候选 | 业务含义 |
|---|---|---|
| segment_summary | SegmentSummaryCandidate | 段摘要和消息范围 |
| relationship_reflection | RelationshipImpactCandidate | 关系维度、方向和离散幅度 |
| state_reflection | StateEntryCandidate | 角色的物理、心境或活动状态 |
| continuity_digest | ContinuityDigestCandidate | 连续性摘要和覆盖到的消息序号 |
| long_term_memory_page | 一个或多个 MemoryUpsertCandidate | 长期记忆页候选 |
| graph_extraction | MemoryEntityCandidate、MemoryEdgeCandidate | 记忆实体和实体关系 |
| diary | DiaryAppendCandidate | 指定游戏日的私人日记 |
| view_refresh | ViewRewriteCandidate、CoreMemoryRewriteCandidate | 关系态度、状态摘要或核心记忆视图 |
| no_op | 无候选 | 明确说明本次没有可提交内容 |

模型不会生成消息序号边界、事实 ID、关系 evidence_kind、记录时间、来源版本或提交状态。需要由 Runtime 生成或复核的字段，不进入模型动作的权威范围。

## 3. 固定图设计

### 3.1 segment_reflect

#### 用途和触发

schedule_segment_reflection(segment_id) 接受一个状态为 sealed 或 ingested 的 MemorySegment。图的来源范围包含段身份、段来源版本、段内消息和关联 Thought；常驻记忆通过 `MemoryContext` 作为上下文读取。段的消息序号范围由 Runtime 读取。

ApplicationRuntime 的 schedule_segment_reflection 是当前模块入口。API 当前提供图运行诊断查询，返回 ReflectionRunView。

#### 拓扑和节点输入输出

~~~mermaid
flowchart TD
    A[segment_summary_plan]
    A -->|follow_up.relationship_reflect| B[relationship_reflect]
    A -->|follow_up.state_reflect| C[state_reflect]
    A --> D[segment_aggregate]
    B --> D
    C --> D
    D --> E[ReflectionBatch review]
~~~

| 节点 | 输入 Contract | 快照字段 | 前置 Artifact | Agent 动作 | Runtime 候选 |
|---|---|---|---|---|---|
| segment_summary_plan | segment_context.v1 | identity、character state、relationship state、memory context、materials | 无 | SegmentSummaryAction，包含 summary 和 FollowUpDecision | SegmentSummaryCandidate |
| relationship_reflect | segment_summary_context.v1 | identity、relationship state、materials | 摘要 Artifact | RelationshipReflectionAction | 一个或多个 RelationshipImpactCandidate |
| state_reflect | segment_summary_context.v1 | identity、character state、materials | 摘要 Artifact | StateReflectionAction | 一个 StateEntryCandidate |
| segment_aggregate | reflection_artifacts.v1 | 无额外快照字段 | 已完成的前置 Artifact | Runtime 聚合，不调用模型 | 图级 ReflectionBatch |

relationship_reflect 和 state_reflect 是条件节点。摘要节点的 FollowUpDecision 只表示是否请求对应节点，最终是否激活仍由 Runtime 根据材料、目标状态和策略决定。

摘要候选的 first_message_sequence 和 last_message_sequence 由 Runtime 从 ReflectionWindowContext 注入。模型只生成摘要文本，不生成消息范围。

#### 图级输出和事实提交

允许的候选类型为：

- 一个 SegmentSummaryCandidate；
- 零个或多个关系影响候选；
- 零个或多个角色状态候选。

有消息材料时必须有一个摘要候选，且摘要范围必须覆盖整段消息。无消息材料时允许显式 no_op。

ReflectionReviewer 当前只审核这一种图。审核通过后，SegmentReflectionChangeSet 分别交给：

- SegmentSummaryHandler：更新 memory_segments.summary_text 和 summary_version；
- RelationshipFactHandler：追加关系证据，使用 Runtime 决定的 RelationshipEvidenceKind.INTERACTION，再按纯规则更新关系状态；
- StateFactHandler：追加角色状态条目，并由 Runtime 决定有效期。

提交成功后，段状态从 sealed 更新为 ingested。图级结果写入 reflection_graph_results，审核和事实数量写入公共 Trace。

### 3.2 continuity_compress

#### 用途和触发

该图把连续的已提交段摘要压缩为一条连续性摘要，供后续会话上下文使用。来源由 Memory 模块的摘要批次选择器提供：memory_summary_batches 保存本次批次的段摘要来源、来源版本和上一条 digest 身份。

连续性批次必须满足：段已处于 ingested、段摘要存在、消息范围在当前批次之前连续、来源版本没有变化。连续性摘要的进度由 covers_through_sequence 表示。

`ReflectionGraphScheduler.schedule_continuity_compression` 接收 `ContinuityCompressionTrigger`，在同一个写事务中冻结摘要批次，再创建以摘要批次为来源的 GraphRun。`ContinuityCompressionGraphSnapshotBuilder` 读取冻结批次、上一条 digest 和当前段摘要，把它们放进 GraphContextSnapshot。它不读取当前批次的原始消息。

批次选择同时受 `limit` 和 `reflection_max_material_chars` 限制。上一条 digest 和当前段摘要按顺序计入同一个材料字符预算；超过预算的后续段留给下一次批次。相同来源版本重复调度时复用已有批次身份和 GraphRun。

#### 拓扑和节点输入输出

~~~mermaid
flowchart LR
    A[continuity_compress] --> B[continuity_aggregate]
    B --> C[ReflectionBatch review]
~~~

| 节点 | 输入 Contract | 快照字段 | 前置 Artifact | Agent 动作 | Runtime 候选 |
|---|---|---|---|---|---|
| continuity_compress | continuity_context.v1 | identity、memory context、materials | 无 | ContinuityDigestAction | ContinuityDigestCandidate |
| continuity_aggregate | reflection_artifacts.v1 | 无额外快照字段 | digest Artifact | Runtime 聚合，不调用模型 | 图级 ReflectionBatch |

ContinuityDigestCandidate 包含摘要正文、覆盖到的消息序号和可选内容版本。模型不决定 digest 身份、来源批次身份或前一条 digest 身份；Runtime 会复核 `covers_through_sequence` 是否等于当前批次最后一条消息序号。已有冻结批次时不接受 `no_op`。

#### 输出消费者和审核

审核通过后，Runtime 调用 MemoryProvenanceRepository.commit_digest，在验证摘要批次来源没有变化后写入 conversation_digests。摘要批次的来源版本、上一条 digest 和覆盖范围会在提交事务中重新验证。提交内容使用现有 `ContinuityDigestAction` 的 6000 字符协议限制；模型返回的可选内容版本不作为数据库权威版本。

摘要批次 Repository 和 digest 提交规则属于该图可以使用的基础设施；图触发、审核和提交已经由 Runtime 按本契约实现。

### 3.3 memory_organize

#### 用途和触发

该图从已经提交的段摘要及其对应的原始消息整理长期记忆和记忆图，避免角色说出的具体细节在摘要中丢失。它与 continuity_compress 使用不同的消费者进度：Memory 模块通过 memory_organization_consumption 记录每个段摘要版本是否已经被长期整理处理。

`ReflectionGraphScheduler.schedule_memory_organization` 接收 `MemoryOrganizationTrigger`，先在同一个写事务中调用 `MemoryProvenanceRepository.freeze_batch(consumer="memory_organize")`，再为冻结批次创建 GraphRun。处理同一摘要版本时复用已有批次身份和 GraphRun；来源版本改变时创建新的图运行。没有新的连续批次时返回空结果，不创建图。

快照不会把长期记忆库全部装入上下文。批次只包含已提交的段摘要；每个段最多读取配置数量的原始消息，`materials` 只保存当前批次的段摘要、消息和 Thought，材料总条数和总字符数受 Reflection 快照预算限制。材料超出预算时保留摘要和预算内的消息，常驻记忆通过 `ContextSnapshotSource.load_character(..., memory_limit=...)` 只取有限条目，并放在 `MemoryContext` 中。模型只能看到当前批次、有限的常驻记忆和身份/状态快照。

#### 拓扑和节点输入输出

~~~mermaid
flowchart LR
    A[page_compose] --> C[memory_aggregate]
    B[graph_extract] --> C
    C --> D[ReflectionBatch review]
~~~

| 节点 | 输入 Contract | 快照字段 | 前置 Artifact | Agent 动作 | Runtime 候选 |
|---|---|---|---|---|---|
| page_compose | memory_organize_context.v1 | identity、memory context、materials | 无 | LongTermMemoryPageAction | MemoryUpsertCandidate |
| graph_extract | memory_organize_context.v1 | identity、memory context、materials | 无 | GraphExtractionAction | MemoryEntityCandidate、MemoryEdgeCandidate |
| memory_aggregate | reflection_artifacts.v1 | 无额外快照字段 | 两个分支 Artifact | Runtime 聚合，不调用模型 | 图级 ReflectionBatch |

page_compose 一次可以提出多个长期记忆页，每个 page 都必须能够独立检索和回想。多个互相独立的约定、承诺、事件或事实分别生成 page；同一内容重复出现时合并为一个 page。每个 page 包含记忆内容、记忆类别、主体和置信度/显著性，整组 page 共用 action 级来源引用。角色自述与玩家陈述须分别引用原始消息；玩家陈述不能直接作为角色已记得共同经历的证据。记忆 ID、来源、可见性、时间和有效期由 Runtime 决定。graph_extract 只提出实体和实体边，实体是否允许写入、是否重复以及边的来源由 Runtime 审核。

实体和关系由 `graph_extract` 一次提出。模型可以同时返回实体和边，Runtime 根据当前批次的实体候选把本地实体键解析为稳定实体 ID；代码不再为同一任务增加独立的实体抽取节点。已有实体通过规范化别名查询复用，新的实体使用稳定身份并登记规范名称别名。重复执行依靠 GraphRun 和候选指纹保持幂等，语义相近但不能确定为同一条记忆的内容保留为独立候选，交给后续人工或产品策略处理。

公共快照参数与任务输入分开：`SnapshotBuildContext` 只携带 `now_utc` 和 SQLite 连接；`SegmentSnapshotPayload` 携带段 ID，`MemoryOrganizationSnapshotPayload` 和 `ContinuityCompressionSnapshotPayload` 携带批次 ID、账户 ID 和角色 ID。`SegmentGraphSnapshotBuilder`、`MemoryOrganizationGraphSnapshotBuilder`、`ContinuityCompressionGraphSnapshotBuilder` 负责不同的来源单位，`GraphSnapshotAssembler` 只组装共同的身份、状态、常驻记忆和快照指纹。

#### 输出消费者和审核

审核通过后，Runtime 在 `MemoryOrganizationCommitService` 的同一个短事务中分别写入：

- memory_entries：长期记忆候选；
- memory_entities：记忆实体候选；
- memory_edges：实体边候选；
- memory_organization_consumption：本摘要批次的消费结果。

记忆内容、记忆图和 memory_views 分属不同语义。该图提交记忆事实后，视图刷新由独立的 view_refresh 策略决定。

审核通过后，记忆候选、实体候选、实体边候选和摘要批次消费记录必须由同一个图级提交事务处理；它们不能绕过 Proposal 审核分别写入。

### 3.4 diary_compose

#### 用途和触发

该图从指定游戏日的 Thought、段摘要和其他允许材料生成一条角色私人日记。触发来源由每日整理策略或明确的叙事结算事件提供；同一角色和游戏日最多保留一条日记记录。

空白游戏日不生成日记。模型只能概括实际存在的材料，不能补写没有来源的生活事件。

#### 拓扑和节点输入输出

~~~mermaid
flowchart LR
    A[diary_compose] --> B[diary_aggregate]
    B --> C[ReflectionBatch review]
~~~

| 节点 | 输入 Contract | 快照字段 | 前置 Artifact | Agent 动作 | Runtime 候选 |
|---|---|---|---|---|---|
| diary_compose | diary_context.v1 | identity、character state、relationship state、memory context、materials | 无 | DiaryAction | DiaryAppendCandidate |
| diary_aggregate | reflection_artifacts.v1 | 无额外快照字段 | diary Artifact | Runtime 聚合，不调用模型 | 图级 ReflectionBatch |

DiaryAppendCandidate 包含 game_day 和日记正文。日记 ID、来源窗口、内容版本、创建时间和 Thought 覆盖清单由 Runtime 生成或计算。

#### 输出消费者和审核

审核通过后，Runtime 应调用 DiaryEntryRepository.ensure 写入 diary_entries，再根据实际覆盖的 Thought 来源调用 Memory provenance 规则。仍被未完成图运行引用的 Thought 不能提前清理。

日记 Repository、来源覆盖和 Thought 清理规则属于该图可以使用的基础设施；图触发、审核和提交由 Runtime 按本契约实现。

### 3.5 view_refresh

#### 用途和触发

该图只处理已经提交的事实产生的派生视图。它不能创造新的记忆、关系事实或角色状态。视图内容可以重建，事实表仍然是权威来源。

触发由 Runtime 的 ViewRefreshPolicy 根据已经提交的 ChangeSet 和视图来源版本决定。关系小幅变化、状态变化和核心记忆变化可以激活不同的视图节点。

#### 拓扑和节点输入输出

~~~mermaid
flowchart TD
    A[view_refresh_planner]
    A -->|relationship_attitude| B[relationship_attitude_view]
    A -->|state_summary| C[state_summary_view]
    A -->|core_memory| D[core_memory_view]
    A --> E[view_aggregate]
    B --> E
    C --> E
    D --> E
    E --> F[ReflectionBatch review]
~~~

| 节点 | 执行方式 | 输入 Contract | 快照字段 | 前置 Artifact | Agent 动作 | Runtime 候选 |
|---|---|---|---|---|---|---|
| view_refresh_planner | Runtime 规则 | change_set.v1 | identity、character state、relationship state、memory context | 无 | Runtime 生成刷新请求 | 不直接产生候选 |
| relationship_attitude_view | Model | view_refresh_request.v1 | identity、relationship state、memory context | planner 请求 | ViewRefreshAction(view_kind=relationship_attitude) | ViewRewriteCandidate |
| state_summary_view | Model | view_refresh_request.v1 | identity、character state、memory context | planner 请求 | ViewRefreshAction(view_kind=state_summary) | ViewRewriteCandidate |
| core_memory_view | Model | view_refresh_request.v1 | identity、memory context | planner 请求 | ViewRefreshAction(view_kind=core_memory) | CoreMemoryRewriteCandidate |
| view_aggregate | Runtime | reflection_artifacts.v1 | 无额外快照字段 | 已完成的刷新 Artifact | Runtime 聚合，不调用模型 | 图级 ReflectionBatch |

视图节点只能引用当前已提交的来源。core_memory_view 必须在候选中提供支持它的记忆 ID；关系态度和状态摘要必须引用对应的事实来源。审核通过后，Runtime 应调用 MemoryViewRepository.upsert，并重新计算 source_snapshot_version。

视图 Repository 和 source_snapshot_version 规则属于该图可以使用的基础设施；ViewRefreshPolicy、刷新请求和提交由 Runtime 按本契约实现。

## 4. 审核、提交和失败规则

### 4.1 共同审核边界

每个图只产生一个 ReflectionBatch 和一个 ProposalEnvelope。审核需要检查：

- Proposal 类型和图身份；
- GraphRun 的来源范围和来源版本；
- 快照身份、节点输入指纹和前置 Artifact 引用；
- 候选来源引用是否属于该图；
- 候选类型是否被该图允许；
- 数量和正文大小是否在预算内；
- 图特有的事实组合、覆盖范围和幂等要求。

审核器按图检查候选类型、来源范围、覆盖范围和幂等条件。SegmentReflectionChangeSet 只用于 segment_reflect，其他图使用各自的提交对象和事实规则。

### 4.2 提交边界

审核通过后，图专用提交服务在一个短写事务中完成本图允许的事实或派生视图写入，并记录图结果。模型调用、来源读取和候选构造不持有该写事务。

失败节点进入重试或失败状态。必需节点失败时，图不能提交部分候选。可选条件节点在重试预算耗尽后保留 failed 状态，聚合节点可以使用其他已经完成的 Artifact；图结果 payload 会记录失败节点、错误码和尝试次数，GraphRun 状态为 partial。partial 仍然经过同一套审核，审核通过后只提交现有候选，调度器不会再次自动领取该运行。后续恢复需要创建新的恢复运行，复用原快照和已完成 Artifact，并只执行失败的可选节点。来源版本变化会创建新的 GraphRun。过期租约和旧执行代数不能修改新运行。

### 4.3 no-op

所有图都允许显式 no_op，但必须提供原因。no_op 表示 Runtime 审核后没有可提交候选。空材料、没有满足刷新策略或没有新的来源时可以产生 no-op，具体条件由各图触发器和审核规则决定。

## 5. 持久化和观测

当前反思运行使用：

- reflection_graph_runs：图运行；
- reflection_node_tasks：节点任务、依赖、租约和状态；
- reflection_artifacts：节点 Artifact；
- reflection_graph_results：图级 Batch 和审核结果。

图结果提交到对应事实表：

| 图 | 事实或视图表 |
|---|---|
| segment_reflect | memory_segments、关系证据和关系状态、character_state_entries |
| continuity_compress | conversation_digests、摘要批次消费来源 |
| memory_organize | memory_entries、memory_entities、memory_edges、组织消费记录 |
| diary_compose | diary_entries、Thought provenance 覆盖记录 |
| view_refresh | memory_views |

公共 Trace 记录图创建、节点领取、模型 step/tool、重试、失败、审核、事实提交和图完成。完整 Artifact、Batch、图结果和事实通过 ReflectionRunView 关联查询；Trace payload 只保存受控摘要，不保存玩家原文、Prompt、完整模型输出或密钥。

## 6. 测试入口

当前已经实现的 Reflection 测试：

- [tests/test_reflection_runtime.py](../../tests/test_reflection_runtime.py)：`segment_reflect`、`continuity_compress` 和 `memory_organize` 运行路径
- [tests/test_reflection_graph_domain.py](../../tests/test_reflection_graph_domain.py)
- [tests/test_reflection_persistence.py](../../tests/test_reflection_persistence.py)
- [tests/test_reflection_node_input.py](../../tests/test_reflection_node_input.py)
- [tests/test_reflection_review.py](../../tests/test_reflection_review.py)：包含连续性摘要边界和 `no_op` 审核
- [tests/test_reflection_snapshot.py](../../tests/test_reflection_snapshot.py)
- [tests/test_reflection_batch.py](../../tests/test_reflection_batch.py)
- [tests/test_reflection_artifact_normalizer.py](../../tests/test_reflection_artifact_normalizer.py)

各图的实现和验证进度见 [implementation-status.md](../implementation-status.md)。
