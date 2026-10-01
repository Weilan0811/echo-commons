# 后端实现状态

> 更新时间：2026-09-30
> 当前判断：后端基础运行时、Conversation 主路径、`segment_reflect`、`continuity_compress` 和 `memory_organize` 已完成代码实现与自动化验证；五种 Reflection Graph 中已有三种接入正式触发、执行、审核和事实提交，`diary_compose`、`view_refresh` 仍只有 Contract、Domain 拓扑和部分持久化基础。自动触发策略、动态记忆取回和完整跨任务模型验证仍未完成。

## 1. 当前结论

后端已经完成从旧反思任务/批次路径到统一 Reflection Graph Runtime 的代码和文档治理。当前唯一正式的 Agent 执行路径是 Echo-native；旧外部 Agent adapter、旧反思任务模型、旧批次 Reviewer 和旧 Runtime Context 已删除。

Conversation 的 T1/T2/T3、消息归段、来源版本、`segment_reflect`、`continuity_compress` 与 `memory_organize` 的 GraphRun/NodeTask/Artifact、图级审核、事实提交、Trace 和失败恢复已经形成可运行路径。`diary_compose`、`view_refresh` 目前只有固定拓扑、节点 Contract、候选类型和部分 Store 能力，尚未有正式调度入口、图专用提交处理器和对应 Runtime 测试。当前项目处于“基础运行时、段反思、连续性压缩和长期记忆整理完成，剩余反思图与自动取回策略待实现”的阶段。

最小可运行路径如下：

```text
玩家消息
  → Conversation T1/T2/T3
  → AgentInvocation / AgentRunResult
  → Proposal 审核
  → SQLite 事实

封口消息段
  → GraphRun / NodeTask
  → NodeInput / Artifact
  → ReflectionBatch / ProposalEnvelope
  → 图级审核
  → 摘要、关系、状态事实

已提交段摘要
  → SummaryBatch（memory_organize consumer）
  → GraphRun / NodeTask
  → 长期记忆页、实体、边
  → 批次消费记录
```

## 2. 已实现能力

| 区域 | 状态 | 代码入口 |
|---|---|---|
| 会话消息接收和同步 | 已实现 | `api/routes/messages.py`、`runtime/conversation/` |
| InputBatch 和 ConversationTask | 已实现 | `store/runtime_repositories.py`、`runtime/dispatcher/` |
| Echo-native Agent Contract | 已实现 | `agents/contracts/`、`agents/harness/` |
| Conversation Prompt 分段和消息顺序 | 已实现 | `agents/harness/context.py`、`agents/harness/prompt.py` |
| Model Gateway | 已实现 | `services/model_gateway/` |
| 分类全局设置 | 已实现 | `config/settings.toml`、`src/echo_server/config.py`；对话、反思生成参数按用途传入模型请求 |
| MemorySegment 和来源版本 | 已实现 | `services/memory/`、`store/memory_repositories.py` |
| SummaryBatch、来源覆盖和消费者进度 | 已实现 | `services/memory/`、`store/memory_provenance.py`、migration `0013`；`continuity_compress` 和 `memory_organize` 已接入独立批次处理 |
| 预置记忆、MemoryContext 和受限检索 | 部分实现 | `services/memory/retrieval.py`、`runtime/memory/search_tool.py`、`services/context/`；动态取回策略和新细节自动整理仍待实现 |
| Reflection Graph Runtime 共享执行骨架 | 已实现 | `runtime/reflection/`、`domain/reflection_graph.py` |
| 五种固定图的 Domain 拓扑和节点 Contract | Contract 已实现；`segment_reflect`、`continuity_compress`、`memory_organize` 接入 Runtime | [`modules/reflection.md`](modules/reflection.md)、`domain/reflection_graph.py`、`agents/contracts/reflection.py` |
| `segment_reflect` 执行、审核和事实提交 | 已实现 | `runtime/reflection/executor.py`、`review.py`、`facts.py` |
| `diary_compose`、`view_refresh` 的正式触发、审核和事实提交 | 待实现 | [`modules/reflection.md`](modules/reflection.md) |
| Graph/Node/Artifact 持久化 | 已实现通用基础设施 | `store/reflection_graph_repositories.py`、migration `0015`、`0016` |
| `segment_reflect` 图级审核和段事实提交 | 已实现 | `runtime/reflection/review.py`、`facts.py` |
| 日记、记忆图和 MemoryView Store | 记忆图已接入 `memory_organize`；日记和 MemoryView 的 Reflection 写入流程待实现 | `store/memory_repositories.py`、migration `0008`、`0013` |
| RelationshipEvidenceKind 规则 | 已实现 | `domain/relationship.py` |
| Trace outbox 和查询 | 已实现 | `observability/trace.py`、`store/trace_repository.py` |
| ReflectionRunView | 已实现 | `observability/reflection_run_view.py`、内部诊断 API |
| Debug Capture | 已实现 | `observability/debug_capture.py`，默认关闭 |
| Runtime 模块组合 | 已实现 | `runtime/application_runtime.py`、`runtime/modules.py` |

## 3. 当前对象边界

- `ApplicationRuntime` 是组合根和公开外观。
- `ConversationModule`、`ReflectionModule`、`MemoryModule`、`ObservabilityModule` 是业务依赖容器。
- `AgentInvocation` 只描述一次 Agent 调用。
- `ProposalEnvelope` 只描述一次待审核提案。
- `ReflectionBatch` 只描述同一 GraphRun 的聚合候选。
- `ReflectionGraphRun`、`ReflectionNodeTask`、`ReflectionArtifact`、`GraphReviewRecord` 分别拥有图、节点、节点输出和审核决定。
- `RelationshipEvidenceKind` 只有 `interaction`、`support`、`conflict`、`commitment` 四个值，由 Runtime 决定。
- `ReflectionGraphScheduler` 已公开 `schedule_segment_reflection`、`schedule_continuity_compression` 和 `schedule_memory_organization`；日记和视图图还没有正式调度入口。

## 4. 持久化状态

当前有效反思表：

- `reflection_graph_runs`
- `reflection_node_tasks`
- `reflection_artifacts`
- `reflection_graph_results`

当前数据库 migration 版本为 `0016`。`0015_reflection_runtime_rebuild.sql` 建立最终四表，`0016_reflection_partial_status.sql` 为可选节点失败后保留 partial 结果补充状态约束；当前有效反思表仍然是最终四表。历史 migration 文件只作为不可变升级历史保留，运行时代码不读取旧表。

## 5. 可观测性状态

Trace 已覆盖消息、任务、图、节点、Agent step/tool、审核和事实提交。已接入的完整业务链路是 `segment_reflect`、`continuity_compress` 和 `memory_organize`；日记和视图图目前只有通用图节点执行和诊断基础设施，没有完整业务事实提交。Trace 通过 outbox 写入，查询服务支持按关联 ID 和业务实体读取。ReflectionRunView 可以从 GraphRun 关联到 NodeTask、Artifact、GraphResult、事实表和 Trace。

普通日志记录服务运行诊断；Debug Capture 只在本地显式开启时保存完整模型 I/O，失败不会改变业务结果。

## 6. 验证基线

当前完整验证基线：

```powershell
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest
uv build
```

还要检查：

- 空数据库执行完整 migration；
- 从 `0014` 升级后只保留最终反思四表；
- Conversation T1/T2/T3 正常；
- 同来源 GraphRun 的运行中重复调度、完成后重复调度、失败后重新执行，以及新消息来源形成新图运行；
- Trace 可以查询到图、节点、Artifact、审核和事实；
- 后端文档链接有效；
- 旧类、旧字段和旧 Agent adapter 路径搜索结果为零（历史 migration 除外）。

归段与重复来源验证已覆盖实际 Conversation 回复和 Thought 入库、消息序号范围、同一次多气泡回复不被拆段、Thought 绑定、段来源版本、GraphRun 和 Artifact、审核后的摘要/关系/状态/来源覆盖、Trace、运行中与完成后的重复调度、重启后重复调度、失败后重新执行，以及新消息形成的新段和新图。封口后的同一段没有公开的来源修改流程；来源变化通过新消息创建新段。重试时按 GraphRun 的创建时刻重建快照，避免等待时间改变输入。

最近一次执行的验证：

```powershell
uv lock --check
uv run ruff check .
uv run ruff format --check .
uv run pytest -q
uv build
```

结果：完整测试集为 313 项通过、1 项跳过；依赖锁定、Ruff 检查、Ruff 格式检查和离线构建通过。新增的 `continuity_compress` 运行测试覆盖两批连续压缩、上一条 digest 传递、材料字符预算、审核和重复调度；`memory_organize` 运行测试覆盖批次冻结、双节点聚合、审核、记忆页/实体/边提交和重复消费；`tests/test_conversation_runtime.py::test_lifespan_worker_completes_the_http_conversation` 已改用正式 Worker 轮询间隔，并按 quiet window 加执行余量计算等待上限。

工作台真实回归已完成 12 个固定脚本运行、4 个 `qwen3:4b` 模拟玩家运行、4 个反思调度、人类玩家接口检查和结果导出检查。另一组 2026-09-29 的 5 个真人运行使用 DeepSeek 执行 `segment_reflect`，5 个图运行都完成并通过审核，未出现无效模型输出。此前的四模型反思回归中 4 个图运行有 2 个完成，DeepSeek 与 Qwen 的 `relationship_reflect` 节点出现 `model_step_budget_exhausted`；失败记录和 Trace 已保留在工作台运行目录。两组结果说明 `segment_reflect` Runtime 可以完成真实提交，跨模型的节点预算和输出稳定性仍需单独处理。

对话盲评已经完成一轮问卷生成和结果分析；当前材料支持对话质量比较。Reflection 产物质量和反思后续效果的完整盲测尚未完成。评审材料没有包含 Thought 内容。

## 7. 开发路线和进度

下面的表是当前开发跟踪表。Reflection 的完整输入、节点输出、候选类型、审核边界和事实消费者见 [`modules/reflection.md`](modules/reflection.md)；本表只记录进度和完成条件。

| 顺序 | 工作项 | 完成条件 | 状态 | 主要入口 |
|---:|---|---|---|---|
| 1 | `segment_reflect` 确定性 Runtime | GraphRun、NodeTask、快照、节点 Artifact、条件节点、ReflectionBatch、Proposal 审核、摘要/状态/关系提交、Trace 和失败后同来源重新执行测试通过 | 已完成 | `runtime/reflection/`、`tests/test_reflection_runtime.py` |
| 2 | 消息归段和来源重复处理验证 | 保存消息序号范围；相同来源不会重复生成有效事实；失败 GraphRun 可以重新执行；新消息来源创建新段与新运行 | 已完成 | `services/memory/sealing.py`、`runtime/reflection/workflow.py`、`tests/test_reflection_runtime.py` |
| 3 | 本地 Agent 测试台 | 运行 Conversation 和 Reflection 实验，保存可复核的原始结果；可查看 GraphRun、NodeTask、Artifact、审核结果、事实结果和 Trace | 已实现 | `server/src/echo_server/api/routes/reflection.py`、本地测试台 |
| 4 | Agent 工具调用与错误恢复 | Provider、Harness、Runtime 三层错误边界和重试计数明确；支持连续工具调用、无进展停止、有限输出修正、任务重试和完整 Trace；Conversation 与 Reflection 失败路径测试通过 | 已实现 | `services/model_gateway/`、`agents/harness/`、`runtime/recovery.py`、`runtime/conversation/`、`runtime/reflection/` |
| 5 | `segment_reflect` 真实 LLM 验证 | 真实模型完成段摘要、可选关系和状态候选；Runtime 完成审核、事实写入、段状态更新、Trace 查询和 SQLite 结果检查 | 部分完成：DeepSeek 真人运行 5/5 完成并通过审核；另一组四模型回归 2/4 完成，DeepSeek 与 Qwen 的 `relationship_reflect` 曾耗尽模型步骤预算；已支持可选节点 partial 结果 | `services/model_gateway/`、`runtime/reflection/`、本地工作台 |
| 6 | `continuity_compress` | 摘要批次触发图运行；生成 `ContinuityDigestCandidate`；审核后写入 `conversation_digests`；批次来源版本和覆盖范围可复核 | 已完成：独立触发器和快照构造、前一条 digest 上下文、材料字符预算、图级审核、事务提交、重复调度、连续覆盖和跨批次测试已通过 | [`modules/reflection.md`](modules/reflection.md) §3.2 |
| 7 | `memory_organize` | 生成长期记忆、实体和边候选；审核后写入对应表；记录摘要批次消费；重复来源保持幂等 | 已完成：批次冻结、独立快照构造、双节点聚合、pages 多记忆页归一化、page_compose/graph_extract Prompt、审核、记忆页/实体/边提交、实体别名去重和消费记录已通过自动化测试 | [`modules/reflection.md`](modules/reflection.md) §3.3 |
| 8 | 对话记忆的取用与延续 | 预置记忆按卡片配置进入上下文；提及往事时能找回相关消息和记忆；角色新讲出的个人细节跨会话保持一致；玩家提出的共同往事不直接成为角色的确定记忆 | 部分实现：预置常驻记忆、来源版本、全文检索、受限搜索工具和 `memory_organize` 提交已实现；自动触发与动态取回仍待实现 | [`modules/memory.md`](modules/memory.md) |
| 9 | `diary_compose` | 按游戏日和实际 Thought/段材料生成日记；审核后写入 `diary_entries`；正确记录来源覆盖并保护未完成任务引用的 Thought | 待实现 | [`modules/reflection.md`](modules/reflection.md) §3.4 |
| 10 | `view_refresh` | Runtime 规则生成刷新请求；按来源变化激活视图节点；审核后更新 `memory_views`；视图来源版本可重新计算 | 待实现 | [`modules/reflection.md`](modules/reflection.md) §3.5 |
| 11 | 完整模型盲测 | 使用真实对话、反思和其他已启用任务，比较任务质量、人格稳定性、结构化输出、延迟、缓存命中和成本，并记录结论 | 部分完成：对话盲评已有一轮结果；Reflection 产物和反思效果、其余图任务仍待测 | [ADR-0006](adr/0006-model-provider-selection.md) |

### Agent 工具调用与错误恢复

本专项的代码实现已经完成；当前只保留统一回归和真实模型验证状态。详细规则见 [`modules/agent-harness.md`](modules/agent-harness.md)、[`modules/model-gateway.md`](modules/model-gateway.md) 和 [`infrastructure/durable-task-runtime.md`](infrastructure/durable-task-runtime.md)；本节只记录实施顺序和完成条件。

| 子顺序 | 工作项 | 完成条件 | 状态 | 主要入口和验证 |
|---:|---|---|---|---|
| 1 | 恢复 Contract 与决策模块 | Gateway、Harness、Runtime 使用稳定错误码和明确恢复动作；Provider、Harness、任务三层计数独立 | 已完成 | `agents/contracts/`、`agents/harness/`、`runtime/recovery.py` |
| 2 | Model Gateway 错误处理 | 供应商错误分类、单请求重试、截止时间和响应错误可分别验证 | 已完成 | `services/model_gateway/`、`tests/test_model_gateway.py` |
| 3 | Harness 工具调用优化 | 支持连续工具调用、多工具结果、输出修正、来源进展判断和软截止时间 | 已完成 | `agents/harness/`、`tests/test_harness_tool_loop.py` |
| 4 | Conversation 恢复接入 | 临时错误可重新执行；不可重试错误立即结束任务；错误和任务尝试可从 Trace 区分；不产生重复消息 | 已完成 | `runtime/conversation/`、`tests/test_runtime_t3.py` |
| 5 | Reflection 恢复接入 | 节点按统一恢复动作重试或结束；可选节点失败后继续聚合已有结果；失败 Agent Run 仍记录 step 和工具 Trace | 已完成 | `runtime/reflection/`、`tests/test_reflection_runtime.py` |
| 6 | 统一回归验证 | 固定故障实验覆盖错误路径；工作台真实模型实验保存完整结果；盲评根据结果另行组织 | 部分完成：代码基线和生命周期集成测试已通过；跨模型反思仍有节点预算失败 | Agent 测试台、工作台运行记录 |

当前进度：自动化验证基线已经稳定；反思节点已允许一次模型输出修正；可选节点失败后会生成带失败明细的 partial 结果，必需节点仍按失败处理。真实运行已证明 `segment_reflect` 可以在审核后写入摘要、关系和状态事实，`continuity_compress` 可以按连续批次写入累计会话摘要，`memory_organize` 可以在同一个 GraphRun 中写入记忆页、实体、边和批次消费。下一步应优先完成剩余两种图的 Runtime 提交，再组织覆盖 Reflection 产物和后续效果的完整盲测。

新文档和新代码统一使用 `segment_reflect`。历史 migration 中的 `segment_ingest` 不代表当前图名称。

## 8. 下一步实施计划

自动化验证基线稳定化已经完成。按当前代码依赖，下一步按以下顺序实施：

1. **完成对话记忆取回与延续**：把消息语境中的往事提及连接到有范围的搜索请求；让角色新讲出的个人细节经过 `memory_organize` 后进入后续会话；补充跨会话检索、来源版本和玩家陈述不能直接成为角色记忆的测试。
2. **接入 `diary_compose` 和 `view_refresh`**：分别完成日记写入与 Thought 来源覆盖、事实变化后的视图规划和视图版本更新；每种图都要有专用审核、提交、幂等和失败恢复验证。
3. **完成模型验证**：先处理 `relationship_reflect` 的模型步骤预算与结构化输出稳定性，再用真实模型重复跨模型回归；之后同时评估 Reflection 产物质量和反思对后续回复的实际影响，补齐完整盲测结论。
