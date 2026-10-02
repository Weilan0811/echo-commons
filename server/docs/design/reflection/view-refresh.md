# view_refresh：把已保存事实整理成易读认识

## 1. 输入及用途

本图读取已经提交的 ChangeSet（事实变化集合），按需要更新关系态度、自身状态摘要和核心记忆视图。输入来自正式关系、状态和长期记忆事实；模型不能通过刷新新增关系证据、改变分数或创建没有来源的经历。

ChangeSet 明确社群、角色、事实种类、具体记录、之前与之后的版本及变化。没有事实变化时不创建刷新请求。刷新频率和哪些变化值得刷新由正式策略决定，当前尚未确定具体阈值，不能杜撰为已经生效的数字。

## 2. 五节点拓扑

```mermaid
flowchart TD
  C[已提交 ChangeSet] --> P[view_refresh_planner<br/>代码规划]
  P --> R[relationship_attitude_view<br/>条件模型节点]
  P --> S[state_summary_view<br/>条件模型节点]
  P --> M[core_memory_view<br/>条件模型节点]
  R --> A[view_aggregate<br/>代码聚合]
  S --> A
  M --> A
  P --> A
  A --> Review[审核与派生视图事务]
```

| 节点 | 输入与条件 | 输出 |
|---|---|---|
| view_refresh_planner | change_set.v1；读取正式变化及当前视图版本 | 目标视图、事实引用、源版本与刷新请求 |
| relationship_attitude_view | view_refresh_request.v1；存在被选中的关系变化 | relationship_attitude 文字及证据 |
| state_summary_view | 存在被选中的状态变化 | state_summary 文字及证据 |
| core_memory_view | 存在被选中的长期记忆变化 | core_memory 文字、supporting_memory_ids 及证据 |
| view_aggregate | reflection_artifacts.v1；规划及已解决分支 | ViewRewriteCandidate、CoreMemoryRewriteCandidate 或 NoOp |

未选分支 skipped；条件分支可以给出明确 NoOp。代码规划器不调用模型，不能根据未提交候选安排刷新。

## 3. 视图内容及审核

ViewRefreshAction 包括 view_kind、content、supporting_memory_ids、evidence_refs。正文最多 6000 字符，支持记忆引用最多 64 项。关系态度表达对明确目标的认识；状态摘要归纳当前有效自身状态；核心记忆选出有实际来源的重要记忆，不新增事实。

每个视图绑定 source_snapshot_version、生成版本、正式事实引用及时间。关系目标属于实际变化范围；核心记忆引用必须属于本实例且仍然有效。审核重新读取源版本，变化后拒绝旧刷新候选，避免旧摘要覆盖新认识。

视图正文使用角色第一人称，表达已保存事实所支持的认识。关系态度不新增证据或增加分数；状态摘要不创造未记录的情绪或身体情况；核心记忆不把他人陈述变成自身确定的亲身经历。关系目标按多角色身份区分。共同表达规则与固定正文见 [反思提示契约](../character-prompt-contracts.md#5-共同反思输出规则)。三个视图节点的专属提示、刷新条件与正式消费者保持未实现。

## 4. 事务、失败和重建

获准的 state_summary 与 core_memory 保存到 memory_views；relationship_attitude 属于明确目标的 relationship_state 态度字段及来源引用。刷新保存与图结果处于同一事务。视图可从正式事实重建，删除视图不删除其事实依据。重复源版本与视图种类不能产生冲突版本。

一个可选分支失败时，其他合法视图可按 partial 规则提交；已经保存的权威关系、状态和记忆事实保持有效。视图失败不回滚此前另一事务中的事实。恢复需要保留成功产物并明确处理尚未刷新目标，见 [共同执行模型](execution-model.md)。

## 5. 运行例子与当前状态

甲对 Alice 的信任增加，并保存一个“下周带棋盘”的长期记忆页。正式事实事务完成后产生 ChangeSet。规划器选择关系态度及核心记忆分支，没有状态变化便跳过状态分支。两个视图形成“我更愿意听她的意见”和带实际记忆引用的近期重点。乙的视图不会随甲变化。

当前存在图定义、行动与候选契约以及派生视图存储；ChangeSet 正式产出、刷新策略、请求准备、节点输入读取、图级规则与视图事实消费者未完整接入。本轮保持未实现，不增加临时自动刷新实现。
