# 反思图与事实提交

行动 JSON 的 `kind` 是必填类型标识。存在实际内容的行动必须填写非空 `evidence_refs`，使用当前材料或前驱产物的明确来源；`no_op` 可以没有证据。提示中的格式规则与正式解析契约采用同一字段要求。模型请求、记忆工具往返与格式修正共用节点预算，默认最多四步、四次模型请求。

实现位于 `modules/reflection/`。ReflectionGraphRegistry 保存固定图定义；ReflectionCoordinator 从真实 MemorySegment 或 SummaryBatch 建立范围明确的图、快照与节点。ReflectionWorkflow 提供显式调度，自动触发政策保持未实现。

| 图 | 当前行为 |
|---|---|
| segment_reflect | 段摘要、关系与状态候选，聚合审核后写入实例事实 |
| continuity_compress | 真实摘要与前一会话摘要压缩，校验来源连续性 |
| memory_organize | 生成记忆页、实体与边，写入真实来源消费 |
| diary_compose、view_refresh | 图与产物契约保留，正式调度和事实提交未实现 |

GraphContext 组合客观观察、角色自身信息与私有记忆；SegmentContext、SummaryContext 分别读取自己的真实来源。ReflectionNodeInput 包含冻结快照与明确的前驱产物，模型节点只提出候选。

ReflectionQueue 负责节点领取、租约、重试与恢复。输入来源在实际模型请求前与提交时复核。ReflectionNodeCommit 原子保存不可变产物、节点状态、后继输入引用和追踪。必需节点失败终止图，可选节点失败仍以实际已完成前驱材料推进。

ReflectionGraphCommit 校验图、当前租约、来源与聚合产物，保存审核决定。ReflectionFacts 将获准候选转换为所属模块的事实写入端口，事实与图结果在同一事务完成；规则拒绝保留审核记录，存储失败回滚整个事务。

ReflectionRunView 按社群与角色返回快照元数据、节点、产物、审核、真实事实和追踪。清除的 Thought 正文在诊断中同样隐藏。字段见 [数据库](../database-design.md)。
