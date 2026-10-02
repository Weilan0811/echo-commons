# 实际数据库说明

基线版本：`0.1.0`；迁移版本：`1`。本文件通过正式初始化服务建立真实空 SQLite 后读取元数据生成，字段与约束以当前 `0001_initial.sql` 和迁移登记结构为依据。

## 业务含义与写入规则

| 事实组 | 所属模块与用途 |
|---|---|
| communities、players、community_members | 社群范围、玩家身份与成员资格 |
| character_instances、character_state_entries、relation_evidence、relationship_state | 独立角色、自身状态及针对 ActorRef 的主观关系认识 |
| conversations、conversation_memberships、messages、message_mentions、message_recipients | 会话、历史成员区间、权威消息及精确受众 |
| input_batches、input_batch_messages | 玩家窗口聚合、角色零窗口输入及所属轮次 |
| social_turns、social_turn_batches、participation_decisions | 多人回应安排、输入来源与每个角色的参与结果 |
| conversation_tasks、conversation_results、thoughts | 持久任务、冻结快照、审核结果与自身内部思考 |
| memory_segments、memory_segment_sources、memory_source_coverage | 精确经历材料、来源身份版本及摘要覆盖 |
| memory_entries、memory_summary_batches、memory_summary_batch_items、conversation_digests | 实例记忆、真实摘要批次与连续会话摘要 |
| memory_entities、memory_entity_aliases、memory_entry_entities、memory_edges、memory_organization_consumption | 记忆组织实体、别名、边、记忆关联及来源消费 |
| memory_search_documents、memory_search_fts | 检索候选与 FTS5 分词索引，返回前仍检查业务读取资格 |
| reflection_graph_runs、reflection_node_tasks、reflection_artifacts、reflection_graph_results | 图、节点、不可变产物及审核结果 |
| diary_entries、memory_views | 保留明确结构；正式消费者与事实提交未实现 |
| trace_outbox、traces、schema_migrations | 独立追踪投递、诊断与成功迁移登记 |

SQLite 保存权威事实，perspective 不建立第二份世界数据。实例通过社群与角色复合引用隔离，成员区间与接收者引用保障历史读取资格。JSON 保存完整输入、候选、审核与有限来源材料，正式业务服务校验其具体契约；需要查询与关联的业务字段独立保存。

`created_at_utc`、`updated_at_utc`、租约截止时间等时间字段统一使用 UTC 文本。`sequence` 是会话中的严格递增消息序号；`version` 和 `generation` 分别标识材料版本与租约代次。具体枚举与数值限制见每张表的建表约束和对应领域契约。

消息与输入、轮次与快照、对话结果与 Thought、反思结果与事实分别在正式短事务中原子保存。模型调用期间不持有写事务。跨表不能单靠外键表达的来源、受众与当前租约规则由正式读取及提交服务验证，见 [事务说明](infrastructure/persistence-and-transactions.md)。

Thought 清除正文保留身份、版本与归段来源。归档和离开保留历史记录；读取与提交按原成员区间处理。摘要覆盖只在真实获准摘要写入后建立；NoOp 不伪造摘要或会话摘要。历史数据库文件保留，当前基线不转换旧格式。

## 字段与约束阅读方式

下列表格列出实际 SQLite 类型、空值、默认值及主键顺序。主键仍以建表语句中的约束为准；JSON 值的详细类型由正式 Python 契约定义。外键按同一编号组合为完整复合引用。索引包含 SQLite 为唯一约束建立的自动索引；FTS5 内部辅助表由 SQLite 管理，不属于业务表。

每张表同时保留其实际建表语句，完整说明 CHECK、UNIQUE、复合键与引用。重新生成执行 `uv run python tools/build_database_reference.py`，验证文档与代码一致执行同一命令加 `--check`。
