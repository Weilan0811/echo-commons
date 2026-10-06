# 实际数据库说明

基线版本：`0.1.0`；迁移版本：`{migration_version}`。本文件通过正式初始化服务建立真实空 SQLite 后读取元数据生成，字段与约束以当前全部 SQL 迁移和迁移登记结构为依据。

## 业务含义与写入规则

| 事实组 | 所属模块与用途 |
|---|---|
| communities、players、community_members | 社群范围、玩家身份与成员资格 |
| character_authoring_drafts、character_authoring_candidates、custom_character_blueprints | 所有者草稿、独立 AI 候选与固定人物版本；确认及实例化规则见 [创作设计](../design/custom-character-authoring.md) |
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

消息与输入、轮次与快照、对话结果与 Thought、反思结果与事实分别在正式短事务中原子保存。模型调用期间不持有写事务。跨表不能单靠外键表达的来源、受众与当前租约规则由正式读取及提交服务验证，见 [事务说明](../design/persistence.md)。

Thought 清除正文保留身份、版本与归段来源。归档和离开保留历史记录；读取与提交按原成员区间处理。摘要覆盖只在真实获准摘要写入后建立；NoOp 不创建摘要。continuity 接受 NoOp 是当前设计差异，见 [实现状态](../status.md)。历史数据库文件保留，当前基线不转换旧格式。

## 逐表业务字段与生命周期

共同 `_id` 表示正式记录身份，community_id/character_id 表示归属；created_at_utc/updated_at_utc 表示记录创建和最后改变，occurred_at_utc 表示来源事件发生，recorded_at_utc 表示记录保存。expires_at_utc 到期后不再作为当前值，invalidated_at_utc 表示失效，数据仍保留来源。以下结合完整 DDL 解释各表特有字段。

| 表 | 特有字段含义及处理边界 |
|---|---|
| communities | timezone/world_time_utc 计算世界当地游戏日；status 控制暂停，state_version 记录世界状态变化 |
| players | display_name 为展示名，player_id 可参与多个社群 |
| community_members | actor_kind/actor_id 登记世界成员，joined_at_utc 保存加入时间；当前没有世界成员历史退出区间 |
| character_instances | blueprint_id/version 固定模板；availability_status/reason/next_check 描述可用资格及计划检查；availability_version 独立递增 |
| character_state_entries | state_kind/value 是某类别状态；state_version 按类别递增，source_kind/ref 去重，期限决定有效值 |
| conversations | kind、status 决定直接/群聊及归档；membership_version 记录成员变化；next_sequence 为下一消息位置 |
| conversation_memberships | joined_after_sequence 为加入时已经存在的最后序号，left_at_sequence 为离开时边界；membership_id 不能复用 |
| input_batches | sender、visibility、audience_json 决定窗口身份；quiet_until 是收集期限，origin_turn_id 只为角色因果来源 |
| social_turns | observation_max_sequence 为共享冻结历史上限，membership_version/audience_json 保存规划资格；completion_json 保存终态说明 |
| social_turn_batches | 精确来源批次及 ordinal，不能凭序号范围补入交错输入 |
| participation_decisions | reason_code 解释选择，selection_order 为规划次序，status/outcome 分别表达执行及发言或沉默 |
| conversation_tasks | snapshot_json 为原输入，membership_id 为原角色区间；attempt、generation、owner、lease_until 共同决定提交资格 |
| conversation_results | 每次 attempt 的 Invocation、契约及 payload；status/decision_code/decided_at 为审核结果，一任务只能有合法唯一批准结果 |
| messages | sequence 确定顺序，sender_membership_id 为发送区间；reply_to/client_message/result/source_turn 分别保存回复、幂等及生成来源 |
| message_mentions | actor_kind/id 表示提及，ordinal 保留明确排列 |
| message_recipients | 新消息绑定发送时的会话成员 membership_id；历史私有消息和旧轮次回应保留原实际受众 |
| input_batch_messages | 一条正式消息只能关联一个来源批次 |
| relation_evidence | observer、target 表示有向认识；evidence_kind 由业务确定，source_kind/ref 为真实证据身份 |
| relationship_state | H/T/A 为当前值；friend_qualifying_evidence_id 保留资格，attitude_summary/source_refs 为派生态度，state_version 表示认识版本 |
| memory_segments | 序号用于定位，source_version 绑定精确材料；sealed 待摘要，ingested 有摘要；summary_text/version 保存在段本身 |
| memory_segment_sources | kind/id/version 和 ordinal 决定实际段材料及顺序 |
| memory_entries | memory_kind/content、subject_kind/id 表示认识和主体；confidence/salience 表示可信及重要程度，visibility 决定常驻或检索方式 |
| thoughts | result_id 关联批准输出，game_day 按世界时间；segment_id 为归段关联；清除 content 后保留身份与 content_removed_at |
| memory_source_coverage | owner_kind/id 表示段摘要或日记，source_kind/id/version 表示精确覆盖，不能只按起止范围登记 |
| memory_summary_batches | source_version 冻结消费者来源集合；previous_digest_id 绑定连续性前驱 |
| memory_summary_batch_items | segment_id、summary_version、ordinal 固定摘要内容及次序 |
| conversation_digests | batch_id 唯一绑定产物，content/version 为正文，covers_through_sequence 为实际覆盖上限 |
| memory_organization_consumption | 每段摘要版本的整理消费，batch_id 为处理来源，outcome 区分 completed/no_op |
| diary_entries | game_day 实例唯一，source_window_kind/ref 记录来源窗口；正式生成消费者未接入 |
| memory_views | core_memory/state_summary、content/version、source_refs_json 与源快照版本；正式刷新未接入 |
| memory_entities | entity_kind/canonical_name 描述角色记忆中的实体，正式标识由后端分配 |
| memory_entity_aliases | alias_text 与 normalized_alias 记录原名及标准比较名，同角色有效别名复用实体 |
| memory_entry_entities | role 表示某实体在记忆页中的关联用途，复合外键限制同角色 |
| memory_edges | from/to、edge_kind、confidence 和可选 source_memory_id；失效保留历史 |
| memory_search_documents | source_kind/id/version 映射合法正式来源，document_id 对应 FTS rowid；内容为可重建投影 |
| memory_search_fts | tokenized_text 用于检索，display_text 展示；内部辅助表由 SQLite 管理 |
| reflection_graph_runs | 图种类/版本、完整 snapshot、source_scope、拓扑/必需/登记节点集合和运行代次；状态说明整个图执行 |
| reflection_node_tasks | dependency_keys、activated 和前驱引用决定就绪，node_input_fingerprint 绑定输入；租约字段保护当前尝试 |
| reflection_artifacts | node_task/attempt 唯一，payload、evidence、audit 与内容身份保存不可变中间产物 |
| reflection_graph_results | graph_run 唯一，aggregate_fingerprint 绑定批次，status/decision/time 记录图审核 |
| trace_outbox | correlation/kind/entity/payload 连接业务阶段，available/lease/attempt 管理独立投递，失败不撤销事实 |
| traces | 保存已经投递的同身份有限事件 |
| schema_migrations | version 与 applied_at_utc 登记成功应用的结构，不保存运行阶段状态 |

## JSON 内部结构

conversation_tasks.snapshot_json 保存 ContextSnapshot，包含 schema_version、prompt_layout_version、snapshot_id、prepared_at_utc、scope、self、environment、perspective、memory、action_space、source_versions；完整设计见 [上下文](../design/perspective-and-context.md)。conversation_results.payload_json 保存本次输出载荷，结果类型和审核身份另有正式字段；Thought 另存私有原文，公开 MessageView 不返回这些字段。

reflection_graph_runs.snapshot_json 保存 GraphContextSnapshot；reflection_artifacts.payload_json 保存节点归一化行动载荷，证据与契约有独立字段；reflection_graph_results.payload_json 保存批次提议，审核决定和理由分别列存储。身份、材料、前驱及证据结构见 [共同执行模型](../design/reflection/execution-model.md) 和五图节点说明。图与节点的可查询状态、范围、租约和来源版本独立列存储，不依赖扫描 JSON 调度。

memory_segments 与 summary_batches 的 source 引用绑定种类、身份、版本及精确覆盖；记忆页来源及实体关联通过关系表查询。trace_outbox/traces 的 payload 只允许事件元数据，完整私有捕获另存文件。JSON 结构由正式类型读取与写入校验，数据库 CHECK 保证 JSON 及必要结构，业务身份和来源仍由服务复核。

## 字段与约束阅读方式

下列表格列出实际 SQLite 类型、空值、默认值及主键顺序。主键仍以建表语句中的约束为准；JSON 值的详细类型由正式 Python 契约定义。外键按同一编号组合为完整复合引用。索引包含 SQLite 为唯一约束建立的自动索引；FTS5 内部辅助表由 SQLite 管理，不属于业务表。

每张表同时保留其实际建表语句，完整说明 CHECK、UNIQUE、复合键与引用。重新生成执行 `uv run python tools/build_database_reference.py`，验证文档与代码一致执行同一命令加 `--check`。
