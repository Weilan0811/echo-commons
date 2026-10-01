# Memory 模块

## 职责和边界

Memory 模块管理对话来源、消息归段、段摘要、Thought、长期记忆、日记、记忆图、派生视图和检索。它向 Conversation 和 Reflection 提供有来源、带版本的上下文材料。

Memory 负责保存和读取这些对象，Runtime 负责决定何时封口、何时触发反思、何时审核并提交候选。Memory 服务不调用 Agent，也不把搜索结果直接写成权威事实。

## 核心对象和持久化

| 对象 | 作用 | 主要表 |
|---|---|---|
| `MemorySegment` | 一段已经封口的连续消息来源窗口 | `memory_segments` |
| `MemorySourceRef` | 一条来源的类型、标识和内容版本 | `memory_source_coverage` 等来源记录 |
| `SummaryBatch` | 一批冻结的段摘要来源，供一个摘要消费者使用 | `memory_summary_batches`、`memory_summary_batch_items` |
| `MemoryEntry` | 可独立检索的长期记忆页 | `memory_entries` |
| `Thought` | 角色回复附带的私有思考，后续可以归入消息段 | `thoughts`、`thought_provenance` |
| `DiaryEntry` | 按 `game_day` 保存的私有日记 | `diary_entries` |
| `MemoryEntity` / `MemoryEdge` | 记忆图的实体和有向关系 | `memory_entities`、`memory_edges` |
| `MemoryView` | 提供给 Agent 的小型派生视图 | `memory_views` |

`messages` 仍然是对话原文的权威来源。MemorySegment 只保存消息序号范围和来源版本，不复制整段消息正文。长期记忆、日记、实体边和视图都必须保留自己的来源引用。

## 来源类型和版本

当前 `MemorySourceKind` 只有三种：

| 类型 | 来源 |
|---|---|
| `message` | 单条消息，版本使用消息身份 |
| `thought` | 一条 Thought，版本使用 Thought 的 `content_version` |
| `segment_summary` | 已提交的段摘要，版本使用该摘要的 `summary_version` |

`MemorySegment.source_version` 表示段当前包含的消息和 Thought 来源集合。封口时先创建段，再绑定该范围内尚未归段的 Thought，并据绑定后的完整来源重新计算版本。因此后续 Reflection 必须使用数据库中重新读取的段版本。

`SummaryBatch.source_version` 表示冻结时选中的摘要来源集合。`MemoryProvenanceRepository` 记录每个消费者对来源的覆盖，防止同一个消费者用不同来源重复提交。

## 输入和输出

输入包括已提交的消息、批准回复产生的 Thought、已审核的 Reflection 结果、摘要批次请求和带范围的检索请求。

输出包括：

- `MemorySegment` 和 `SegmentSummary` 上下文材料；
- `MemoryEntry`、`DiaryEntry`、`MemoryEntity`、`MemoryEdge` 和 `MemoryView`；
- `SummaryBatch`、`ConversationDigest` 和记忆组织消费记录；
- 带 `expected_source_version`、会话范围和最大消息序号的检索结果；
- 供 Context Snapshot 使用的 `MemoryContext` 和 `ContextSourceSnapshot`。

## 主流程

### 消息归段

`MemorySegmentSealingService.seal_unsegmented_messages` 在一个短写事务中：

1. 检查会话和唯一活跃角色。
2. 读取尚未覆盖的连续消息，可选地限制到指定消息序号。
3. 避免把一次多气泡角色回复从中间截断；如果范围会拆开回复组，就退回到完整回复组之前。
4. 创建 `sealed` 状态的 `MemorySegment`，持久保存 `first_message_sequence`、`last_message_sequence` 和初始来源版本。
5. 把范围内的 Thought 绑定到段，并按完整来源更新 `source_version`。

这个服务只建立稳定来源窗口，不调用 Agent，也不自动创建 Reflection Graph。何时触发图由 Application Runtime 或其他显式触发器决定。

### 段摘要和事实提交

`segment_reflect` 读取 `sealed` 段及其来源材料。审核通过后，Reflection Runtime 在一个事务中提交段摘要、关系事实、角色状态事实和来源覆盖；提交成功后把段从 `sealed` 改为 `ingested`。摘要必须匹配段的消息序号范围和 `source_version`，来源覆盖必须与数据库重新读取的消息和 Thought 集合完全一致。

段已经 `ingested` 后不能由普通摘要写入路径再次修改。新的消息会形成新的段；来源变化需要由明确的重建流程处理。

### 摘要批次和独立消费者

`MemoryProvenanceRepository.freeze_batch` 按消息范围选择已完成的段摘要并创建冻结批次。当前允许的消费者是：

- `continuity_compress`：生成会话连续性摘要 `ConversationDigest`，记录 `covers_through_sequence` 和前一个摘要；当前已经接入 Reflection Runtime 的批次冻结、快照、审核和提交。
- `memory_organize`：消费同一类段摘要，生成长期记忆、实体、边或其它组织结果。当前已由 Reflection Runtime 接入批次冻结、GraphRun、审核和提交。

两个消费者有独立的覆盖记录和提交入口。它们可以读取相同的段摘要，但不能共用一条“已处理”标记来代替各自的来源记录。

`memory_organize` 的上下文按批次读取。每个批次只包含有限数量的已提交段摘要；构造快照时按每段消息预算读取原始消息，材料总数量和总字符数继续受到 Reflection 快照预算限制。超出预算的原始消息不会继续扩大上下文，段摘要仍然可以作为整理依据。常驻记忆通过受限的 `MemoryContext` 进入，长期记忆库的全部内容不会进入一次模型调用。

`continuity_compress` 只读取上一条连续性摘要和当前批次的段摘要。两类材料共同使用 Reflection 的字符预算，超过预算的后续段留给下一次连续性批次；它不会把原始消息或完整长期记忆库装入模型上下文。

### 读取和检索

`ContextSourceSnapshot` 从状态、关系、记忆视图、段摘要和会话摘要组成稳定快照。启用 `memory_search` 时，`MemorySearchService` 使用快照中的搜索版本、会话范围和 `frozen_max_sequence` 限制查询边界。搜索返回的是可引用的记忆材料，不会直接改变 `memory_entries` 或其它事实表。

角色可以讲述未预先写入记忆的个人日常；具体细节一旦说出，消息便成为后续整理和回忆的来源。涉及双方共同经历时，须区分已有对话或事件记录与玩家当前的陈述：后者证明玩家这样说过，不能直接变成角色自身的确定记忆。习惯和关系感受可以来自人物设定、关系状态或记忆，但不能据此补出具体的共同事件。

当前消息和长期记忆已建立检索索引，但可检索不等于本轮已取回；预置条目只有设为 `resident` 才会直接进入上下文。对话前按往事话题取回相关材料，以及把 `memory_organize` 接入自动触发策略，仍待实现。

## 状态和失败

`MemorySegment` 只有 `sealed` 和 `ingested` 两个状态。封口前必须有有效的连续消息范围；`sealed` 段必须经过版本检查才能写摘要；`ingested` 段必须有 `ingested_at_utc`。

以下情况会拒绝本次操作并回滚调用方事务：

- 消息范围为空、倒序或会截断一次角色回复；
- 段来源版本与 Graph Snapshot 不一致；
- 摘要范围与段范围不一致；
- 来源覆盖缺少消息或 Thought，或重放时来源集合不同；
- 同一状态版本、摘要消费者或来源身份发生冲突。
- `memory_organize` 的实体规范化名称已经存在于别名索引且指向同一实体时会复用该实体；同一 GraphRun 的记忆页、实体、边和消费记录在一个事务中提交，任意一项失败都会回滚本次提交。

检索不可用时返回稳定服务错误。常驻记忆、近期消息、Thought、段摘要和搜索结果继续保持独立来源，调用方不能把它们拼成一个没有来源的文本字段。

## 事务和幂等

封口、摘要提交、来源覆盖、摘要批次冻结和记忆组织提交都由调用方明确提供写事务。模型调用期间不持有该事务。

来源覆盖以 `owner_kind + owner_id + source kind + source_id + source_version` 识别。已存在的覆盖必须与本次完全相同；不同版本或不同集合会报告重放不一致。Memory 的事实写入必须经过对应 Reflection Proposal 的审核结果，不能由搜索或普通读取路径绕过审核。

## Trace 和日志

Trace 记录段封口、段来源绑定、摘要批次冻结、检索开始和结束、来源版本冲突、Reflection 事实提交数量以及各消费者的提交结果。Trace payload 只保留范围、版本、数量、消费者和错误码，不保存玩家原文、完整 Thought 或完整记忆正文。

日志用于记录耗时、数据库错误和搜索服务状态。需要查看正文时，通过 `segment_id`、`memory_id`、`diary_id` 或来源引用查询对应事实表。

## 测试入口

- `server/tests/test_memory_foundation.py`：Memory 基础对象和持久化。
- `server/tests/test_memory_search_and_sealing.py`：消息归段、搜索范围和来源版本。
- `server/tests/test_reflection_persistence.py`：Reflection 对摘要和来源的提交。
- `server/tests/test_reflection_runtime.py`：`segment_reflect`、`memory_organize` 图运行与 Memory 提交路径。
- `server/tests/test_domain_invariants.py`、`server/tests/test_migrations.py`：领域不变量和表结构。
