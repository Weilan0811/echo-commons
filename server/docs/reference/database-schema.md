# 实际数据库说明

基线版本：`0.1.0`；迁移版本：`2`。本文件通过正式初始化服务建立真实空 SQLite 后读取元数据生成，字段与约束以当前全部 SQL 迁移和迁移登记结构为依据。`0002_social_turn_states.sql` 保留已有数据，移除社会轮次的 pending 许可。

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
| message_recipients | 公共及私有消息均绑定实际 membership_id 受众 |
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

实际登记 46 张表，包含迁移登记及 FTS5 虚拟表。


## `schema_migrations`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `version` | INTEGER | 是 | — | 1 |
| `applied_at_utc` | TEXT | 否 | — | — |

### 完整建表约束

```sql
CREATE TABLE schema_migrations (version INTEGER PRIMARY KEY CHECK(version > 0), applied_at_utc TEXT NOT NULL);
```


## `communities`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `community_id` | TEXT | 否 | — | 1 |
| `name` | TEXT | 否 | — | — |
| `timezone` | TEXT | 否 | — | — |
| `world_time_utc` | TEXT | 否 | — | — |
| `status` | TEXT | 否 | 'active' | — |
| `state_version` | INTEGER | 否 | 0 | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_communities_1` | 是 | community_id | 否 |

### 完整建表约束

```sql
CREATE TABLE communities (
    community_id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    timezone TEXT NOT NULL,
    world_time_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused')),
    state_version INTEGER NOT NULL DEFAULT 0 CHECK(state_version >= 0),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL
);
```


## `players`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `player_id` | TEXT | 否 | — | 1 |
| `display_name` | TEXT | 否 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_players_1` | 是 | player_id | 否 |

### 完整建表约束

```sql
CREATE TABLE players (
    player_id TEXT PRIMARY KEY NOT NULL,
    display_name TEXT NOT NULL CHECK(length(trim(display_name)) > 0),
    created_at_utc TEXT NOT NULL
);
```


## `community_members`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `community_id` | TEXT | 否 | — | 1 |
| `actor_kind` | TEXT | 否 | — | 2 |
| `actor_id` | TEXT | 否 | — | 3 |
| `joined_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `communities` | `community_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_community_members_1` | 是 | community_id, actor_kind, actor_id | 否 |

### 完整建表约束

```sql
CREATE TABLE community_members (
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    actor_kind TEXT NOT NULL CHECK(actor_kind IN ('player','character')),
    actor_id TEXT NOT NULL, joined_at_utc TEXT NOT NULL,
    PRIMARY KEY(community_id, actor_kind, actor_id)
);
```


## `character_instances`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `character_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `blueprint_id` | TEXT | 否 | — | — |
| `blueprint_version` | TEXT | 否 | — | — |
| `availability_status` | TEXT | 否 | 'available' | — |
| `availability_reason` | TEXT | 是 | — | — |
| `next_check_at_utc` | TEXT | 是 | — | — |
| `availability_version` | INTEGER | 否 | 0 | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `communities` | `community_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_character_instances_2` | 是 | community_id, character_id | 否 |
| `sqlite_autoindex_character_instances_1` | 是 | character_id | 否 |

### 完整建表约束

```sql
CREATE TABLE character_instances (
    character_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    blueprint_id TEXT NOT NULL, blueprint_version TEXT NOT NULL,
    availability_status TEXT NOT NULL DEFAULT 'available'
        CHECK(availability_status IN ('available','offline','busy')),
    availability_reason TEXT, next_check_at_utc TEXT,
    availability_version INTEGER NOT NULL DEFAULT 0 CHECK(availability_version >= 0),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    UNIQUE(community_id, character_id)
);
```


## `character_state_entries`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `entry_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | — |
| `state_kind` | TEXT | 否 | — | — |
| `value` | TEXT | 否 | — | — |
| `source_kind` | TEXT | 否 | — | — |
| `source_ref` | TEXT | 否 | — | — |
| `state_version` | INTEGER | 否 | — | — |
| `recorded_at_utc` | TEXT | 否 | — | — |
| `expires_at_utc` | TEXT | 是 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 0 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `state_latest` | 否 | character_id, state_kind, state_version | 否 |

```sql
CREATE INDEX state_latest ON character_state_entries(character_id, state_kind, state_version DESC);
```

| `sqlite_autoindex_character_state_entries_3` | 是 | character_id, state_kind, source_kind, source_ref | 否 |
| `sqlite_autoindex_character_state_entries_2` | 是 | character_id, state_kind, state_version | 否 |
| `sqlite_autoindex_character_state_entries_1` | 是 | entry_id | 否 |

### 完整建表约束

```sql
CREATE TABLE character_state_entries (
    entry_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    state_kind TEXT NOT NULL CHECK(state_kind IN ('physical','mood','activity')),
    value TEXT NOT NULL, source_kind TEXT NOT NULL, source_ref TEXT NOT NULL,
    state_version INTEGER NOT NULL CHECK(state_version >= 1),
    recorded_at_utc TEXT NOT NULL, expires_at_utc TEXT,
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    CHECK(expires_at_utc IS NULL OR expires_at_utc > recorded_at_utc),
    UNIQUE(character_id, state_kind, state_version),
    UNIQUE(character_id, state_kind, source_kind, source_ref)
);
```


## `conversations`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `conversation_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `kind` | TEXT | 否 | — | — |
| `status` | TEXT | 否 | 'active' | — |
| `membership_version` | INTEGER | 否 | 0 | — |
| `next_sequence` | INTEGER | 否 | 1 | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `communities` | `community_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `conversations_community` | 否 | community_id, created_at_utc, conversation_id | 否 |

```sql
CREATE INDEX conversations_community ON conversations(community_id, created_at_utc, conversation_id);
```

| `sqlite_autoindex_conversations_2` | 是 | community_id, conversation_id | 否 |
| `sqlite_autoindex_conversations_1` | 是 | conversation_id | 否 |

### 完整建表约束

```sql
CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    kind TEXT NOT NULL CHECK(kind IN ('direct','group')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    membership_version INTEGER NOT NULL DEFAULT 0 CHECK(membership_version >= 0),
    next_sequence INTEGER NOT NULL DEFAULT 1 CHECK(next_sequence >= 1),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    UNIQUE(community_id, conversation_id)
);
```


## `conversation_memberships`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `membership_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `conversation_id` | TEXT | 否 | — | — |
| `actor_kind` | TEXT | 否 | — | — |
| `actor_id` | TEXT | 否 | — | — |
| `joined_after_sequence` | INTEGER | 否 | — | — |
| `left_at_sequence` | INTEGER | 是 | — | — |
| `joined_at_utc` | TEXT | 否 | — | — |
| `left_at_utc` | TEXT | 是 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `community_members` | `community_id` | NO ACTION | NO ACTION |
| 0 | `actor_kind` | `community_members` | `actor_kind` | NO ACTION | NO ACTION |
| 0 | `actor_id` | `community_members` | `actor_id` | NO ACTION | NO ACTION |
| 1 | `community_id` | `conversations` | `community_id` | NO ACTION | NO ACTION |
| 1 | `conversation_id` | `conversations` | `conversation_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `memberships_history` | 否 | conversation_id, actor_kind, actor_id, joined_after_sequence | 否 |

```sql
CREATE INDEX memberships_history ON conversation_memberships(conversation_id, actor_kind, actor_id, joined_after_sequence);
```

| `memberships_current` | 是 | conversation_id, actor_kind, actor_id | 是 |

```sql
CREATE UNIQUE INDEX memberships_current ON conversation_memberships(conversation_id, actor_kind, actor_id) WHERE left_at_utc IS NULL;
```

| `sqlite_autoindex_conversation_memberships_3` | 是 | community_id, conversation_id, membership_id | 否 |
| `sqlite_autoindex_conversation_memberships_2` | 是 | conversation_id, membership_id | 否 |
| `sqlite_autoindex_conversation_memberships_1` | 是 | membership_id | 否 |

### 完整建表约束

```sql
CREATE TABLE conversation_memberships (
    membership_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    actor_kind TEXT NOT NULL CHECK(actor_kind IN ('player','character')), actor_id TEXT NOT NULL,
    joined_after_sequence INTEGER NOT NULL CHECK(joined_after_sequence >= 0),
    left_at_sequence INTEGER, joined_at_utc TEXT NOT NULL, left_at_utc TEXT,
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    FOREIGN KEY(community_id, actor_kind, actor_id) REFERENCES community_members(community_id, actor_kind, actor_id),
    UNIQUE(conversation_id, membership_id),
    UNIQUE(community_id, conversation_id, membership_id),
    CHECK((left_at_sequence IS NULL AND left_at_utc IS NULL) OR
        (left_at_sequence IS NOT NULL AND left_at_utc IS NOT NULL AND
         left_at_sequence >= joined_after_sequence AND left_at_utc >= joined_at_utc))
);
```


## `input_batches`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `input_batch_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `conversation_id` | TEXT | 否 | — | — |
| `sender_kind` | TEXT | 否 | — | — |
| `sender_id` | TEXT | 否 | — | — |
| `visibility` | TEXT | 否 | — | — |
| `audience_json` | TEXT | 否 | — | — |
| `status` | TEXT | 否 | — | — |
| `quiet_until_utc` | TEXT | 否 | — | — |
| `sealed_at_utc` | TEXT | 是 | — | — |
| `origin_turn_id` | TEXT | 是 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `conversations` | `community_id` | NO ACTION | NO ACTION |
| 0 | `conversation_id` | `conversations` | `conversation_id` | NO ACTION | NO ACTION |
| 1 | `origin_turn_id` | `social_turns` | `social_turn_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `batches_due` | 否 | status, sender_kind, quiet_until_utc, created_at_utc | 否 |

```sql
CREATE INDEX batches_due ON input_batches(status, sender_kind, quiet_until_utc, created_at_utc);
```

| `batches_collecting` | 是 | conversation_id, sender_kind, sender_id, visibility, audience_json | 是 |

```sql
CREATE UNIQUE INDEX batches_collecting ON input_batches(conversation_id, sender_kind, sender_id, visibility, audience_json) WHERE status = 'collecting';
```

| `sqlite_autoindex_input_batches_2` | 是 | conversation_id, input_batch_id | 否 |
| `sqlite_autoindex_input_batches_1` | 是 | input_batch_id | 否 |

### 完整建表约束

```sql
CREATE TABLE input_batches (
    input_batch_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    sender_kind TEXT NOT NULL CHECK(sender_kind IN ('player','character')), sender_id TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK(visibility IN ('conversation','recipients')),
    audience_json TEXT NOT NULL CHECK(json_valid(audience_json) AND json_type(audience_json) = 'array'),
    status TEXT NOT NULL CHECK(status IN ('collecting','sealed')),
    quiet_until_utc TEXT NOT NULL, sealed_at_utc TEXT,
    origin_turn_id TEXT REFERENCES social_turns(social_turn_id),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    CHECK((status = 'collecting' AND sealed_at_utc IS NULL) OR
          (status = 'sealed' AND sealed_at_utc IS NOT NULL)),
    CHECK(sender_kind != 'character' OR (status = 'sealed' AND origin_turn_id IS NOT NULL)),
    CHECK(sender_kind != 'player' OR origin_turn_id IS NULL),
    UNIQUE(conversation_id, input_batch_id)
);
```


## `social_turn_batches`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `social_turn_id` | TEXT | 否 | — | 1 |
| `input_batch_id` | TEXT | 否 | — | 2 |
| `ordinal` | INTEGER | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `input_batch_id` | `input_batches` | `input_batch_id` | NO ACTION | NO ACTION |
| 1 | `social_turn_id` | `social_turns` | `social_turn_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_social_turn_batches_3` | 是 | social_turn_id, ordinal | 否 |
| `sqlite_autoindex_social_turn_batches_2` | 是 | social_turn_id, input_batch_id | 否 |
| `sqlite_autoindex_social_turn_batches_1` | 是 | input_batch_id | 否 |

### 完整建表约束

```sql
CREATE TABLE social_turn_batches (
    social_turn_id TEXT NOT NULL REFERENCES social_turns(social_turn_id),
    input_batch_id TEXT NOT NULL UNIQUE REFERENCES input_batches(input_batch_id),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(social_turn_id, input_batch_id), UNIQUE(social_turn_id, ordinal)
);
```


## `participation_decisions`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `social_turn_id` | TEXT | 否 | — | 1 |
| `character_id` | TEXT | 否 | — | 2 |
| `reason_code` | TEXT | 否 | — | — |
| `selection_order` | INTEGER | 是 | — | — |
| `status` | TEXT | 否 | — | — |
| `outcome` | TEXT | 是 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |
| 1 | `social_turn_id` | `social_turns` | `social_turn_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_participation_decisions_1` | 是 | social_turn_id, character_id | 否 |

### 完整建表约束

```sql
CREATE TABLE participation_decisions (
    social_turn_id TEXT NOT NULL REFERENCES social_turns(social_turn_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    reason_code TEXT NOT NULL, selection_order INTEGER CHECK(selection_order >= 0),
    status TEXT NOT NULL CHECK(status IN ('silent','selected','completed','failed','cancelled')),
    outcome TEXT, updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(social_turn_id, character_id),
    CHECK((status = 'selected' AND outcome IS NULL) OR (status != 'selected' AND outcome IS NOT NULL)),
    CHECK((status = 'silent' AND selection_order IS NULL AND outcome = 'silent') OR
          (status = 'selected' AND selection_order IS NOT NULL AND outcome IS NULL) OR
          (status = 'completed' AND selection_order IS NOT NULL AND outcome IN ('message','silent')) OR
          (status = 'failed' AND selection_order IS NOT NULL AND outcome = 'failed') OR
          (status = 'cancelled' AND selection_order IS NOT NULL AND outcome = 'cancelled'))
);
```


## `conversation_tasks`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `task_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `conversation_id` | TEXT | 否 | — | — |
| `social_turn_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | — |
| `membership_id` | TEXT | 否 | — | — |
| `snapshot_id` | TEXT | 否 | — | — |
| `snapshot_schema_version` | INTEGER | 否 | 1 | — |
| `snapshot_json` | TEXT | 否 | — | — |
| `status` | TEXT | 否 | — | — |
| `attempt_count` | INTEGER | 否 | 0 | — |
| `lease_generation` | INTEGER | 否 | 0 | — |
| `available_at_utc` | TEXT | 否 | — | — |
| `lease_owner` | TEXT | 是 | — | — |
| `lease_until_utc` | TEXT | 是 | — | — |
| `last_error_code` | TEXT | 是 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |
| `trace_id` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `conversation_memberships` | `community_id` | NO ACTION | NO ACTION |
| 0 | `conversation_id` | `conversation_memberships` | `conversation_id` | NO ACTION | NO ACTION |
| 0 | `membership_id` | `conversation_memberships` | `membership_id` | NO ACTION | NO ACTION |
| 1 | `social_turn_id` | `participation_decisions` | `social_turn_id` | NO ACTION | NO ACTION |
| 1 | `character_id` | `participation_decisions` | `character_id` | NO ACTION | NO ACTION |
| 2 | `community_id` | `social_turns` | `community_id` | NO ACTION | NO ACTION |
| 2 | `conversation_id` | `social_turns` | `conversation_id` | NO ACTION | NO ACTION |
| 2 | `social_turn_id` | `social_turns` | `social_turn_id` | NO ACTION | NO ACTION |
| 3 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 3 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `tasks_claim` | 否 | status, available_at_utc, created_at_utc, task_id | 否 |

```sql
CREATE INDEX tasks_claim ON conversation_tasks(status, available_at_utc, created_at_utc, task_id);
```

| `sqlite_autoindex_conversation_tasks_3` | 是 | social_turn_id, character_id | 否 |
| `sqlite_autoindex_conversation_tasks_2` | 是 | snapshot_id | 否 |
| `sqlite_autoindex_conversation_tasks_1` | 是 | task_id | 否 |

### 完整建表约束

```sql
CREATE TABLE conversation_tasks (
    task_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    social_turn_id TEXT NOT NULL, character_id TEXT NOT NULL, membership_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL UNIQUE,
    snapshot_schema_version INTEGER NOT NULL DEFAULT 1 CHECK(snapshot_schema_version = 1),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','processing','retry_wait','suspended','completed','failed','cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0),
    available_at_utc TEXT NOT NULL, lease_owner TEXT, lease_until_utc TEXT, last_error_code TEXT,
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL, trace_id TEXT NOT NULL,
    UNIQUE(social_turn_id, character_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, conversation_id, social_turn_id) REFERENCES social_turns(community_id, conversation_id, social_turn_id),
    FOREIGN KEY(social_turn_id, character_id) REFERENCES participation_decisions(social_turn_id, character_id),
    FOREIGN KEY(community_id, conversation_id, membership_id) REFERENCES conversation_memberships(community_id, conversation_id, membership_id),
    CHECK((status = 'processing' AND lease_owner IS NOT NULL AND lease_until_utc IS NOT NULL)
       OR (status != 'processing' AND lease_owner IS NULL AND lease_until_utc IS NULL))
);
```


## `conversation_results`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `result_id` | TEXT | 否 | — | 1 |
| `task_id` | TEXT | 否 | — | — |
| `attempt_no` | INTEGER | 否 | — | — |
| `lease_generation` | INTEGER | 否 | — | — |
| `invocation_id` | TEXT | 否 | — | — |
| `output_contract` | TEXT | 否 | — | — |
| `payload_json` | TEXT | 否 | — | — |
| `status` | TEXT | 否 | — | — |
| `decision_code` | TEXT | 是 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `decided_at_utc` | TEXT | 是 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `task_id` | `conversation_tasks` | `task_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `results_approved` | 是 | task_id | 是 |

```sql
CREATE UNIQUE INDEX results_approved ON conversation_results(task_id) WHERE status = 'approved';
```

| `sqlite_autoindex_conversation_results_3` | 是 | task_id, attempt_no | 否 |
| `sqlite_autoindex_conversation_results_2` | 是 | invocation_id | 否 |
| `sqlite_autoindex_conversation_results_1` | 是 | result_id | 否 |

### 完整建表约束

```sql
CREATE TABLE conversation_results (
    result_id TEXT PRIMARY KEY NOT NULL, task_id TEXT NOT NULL REFERENCES conversation_tasks(task_id),
    attempt_no INTEGER NOT NULL CHECK(attempt_no >= 1), lease_generation INTEGER NOT NULL CHECK(lease_generation >= 1),
    invocation_id TEXT NOT NULL UNIQUE, output_contract TEXT NOT NULL CHECK(output_contract = 'character_message.v1'),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','expired')),
    decision_code TEXT, created_at_utc TEXT NOT NULL, decided_at_utc TEXT,
    UNIQUE(task_id, attempt_no),
    CHECK((status = 'pending' AND decision_code IS NULL AND decided_at_utc IS NULL) OR
          (status != 'pending' AND decision_code IS NOT NULL AND decided_at_utc IS NOT NULL))
);
```


## `messages`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `message_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `conversation_id` | TEXT | 否 | — | — |
| `sequence` | INTEGER | 否 | — | — |
| `sender_kind` | TEXT | 否 | — | — |
| `sender_id` | TEXT | 否 | — | — |
| `sender_membership_id` | TEXT | 是 | — | — |
| `text` | TEXT | 否 | — | — |
| `visibility` | TEXT | 否 | — | — |
| `reply_to_message_id` | TEXT | 是 | — | — |
| `client_message_id` | TEXT | 是 | — | — |
| `source_turn_id` | TEXT | 是 | — | — |
| `result_id` | TEXT | 是 | — | — |
| `trace_id` | TEXT | 否 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `social_turns` | `community_id` | NO ACTION | NO ACTION |
| 0 | `conversation_id` | `social_turns` | `conversation_id` | NO ACTION | NO ACTION |
| 0 | `source_turn_id` | `social_turns` | `social_turn_id` | NO ACTION | NO ACTION |
| 1 | `conversation_id` | `messages` | `conversation_id` | NO ACTION | NO ACTION |
| 1 | `reply_to_message_id` | `messages` | `message_id` | NO ACTION | NO ACTION |
| 2 | `conversation_id` | `conversation_memberships` | `conversation_id` | NO ACTION | NO ACTION |
| 2 | `sender_membership_id` | `conversation_memberships` | `membership_id` | NO ACTION | NO ACTION |
| 3 | `community_id` | `conversations` | `community_id` | NO ACTION | NO ACTION |
| 3 | `conversation_id` | `conversations` | `conversation_id` | NO ACTION | NO ACTION |
| 4 | `result_id` | `conversation_results` | `result_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `messages_client` | 是 | sender_id, client_message_id | 是 |

```sql
CREATE UNIQUE INDEX messages_client ON messages(sender_id, client_message_id) WHERE sender_kind = 'player';
```

| `sqlite_autoindex_messages_4` | 是 | conversation_id, message_id | 否 |
| `sqlite_autoindex_messages_3` | 是 | conversation_id, sequence | 否 |
| `sqlite_autoindex_messages_2` | 是 | result_id | 否 |
| `sqlite_autoindex_messages_1` | 是 | message_id | 否 |

### 完整建表约束

```sql
CREATE TABLE messages (
    message_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence >= 1),
    sender_kind TEXT NOT NULL CHECK(sender_kind IN ('player','character','system')), sender_id TEXT NOT NULL,
    sender_membership_id TEXT,
    text TEXT NOT NULL CHECK(length(trim(text)) > 0),
    visibility TEXT NOT NULL CHECK(visibility IN ('conversation','recipients')),
    reply_to_message_id TEXT, client_message_id TEXT,
    source_turn_id TEXT, result_id TEXT UNIQUE REFERENCES conversation_results(result_id),
    trace_id TEXT NOT NULL, created_at_utc TEXT NOT NULL,
    UNIQUE(conversation_id, sequence), UNIQUE(conversation_id, message_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    FOREIGN KEY(conversation_id, sender_membership_id) REFERENCES conversation_memberships(conversation_id, membership_id),
    FOREIGN KEY(conversation_id, reply_to_message_id) REFERENCES messages(conversation_id, message_id),
    FOREIGN KEY(community_id, conversation_id, source_turn_id) REFERENCES social_turns(community_id, conversation_id, social_turn_id),
    CHECK((sender_kind = 'system' AND sender_membership_id IS NULL) OR
          (sender_kind != 'system' AND sender_membership_id IS NOT NULL)),
    CHECK(sender_kind != 'player' OR (client_message_id IS NOT NULL AND result_id IS NULL AND source_turn_id IS NULL)),
    CHECK(sender_kind != 'character' OR (result_id IS NOT NULL AND source_turn_id IS NOT NULL AND client_message_id IS NULL)),
    CHECK(sender_kind = 'player' OR client_message_id IS NULL)
);
```


## `message_mentions`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `message_id` | TEXT | 否 | — | 1 |
| `actor_kind` | TEXT | 否 | — | 2 |
| `actor_id` | TEXT | 否 | — | 3 |
| `ordinal` | INTEGER | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `message_id` | `messages` | `message_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_message_mentions_2` | 是 | message_id, ordinal | 否 |
| `sqlite_autoindex_message_mentions_1` | 是 | message_id, actor_kind, actor_id | 否 |

### 完整建表约束

```sql
CREATE TABLE message_mentions (
    message_id TEXT NOT NULL REFERENCES messages(message_id),
    actor_kind TEXT NOT NULL CHECK(actor_kind IN ('player','character')), actor_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(message_id, actor_kind, actor_id), UNIQUE(message_id, ordinal)
);
```


## `message_recipients`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `message_id` | TEXT | 否 | — | 1 |
| `membership_id` | TEXT | 否 | — | 2 |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `membership_id` | `conversation_memberships` | `membership_id` | NO ACTION | NO ACTION |
| 1 | `message_id` | `messages` | `message_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `recipients_membership` | 否 | membership_id, message_id | 否 |

```sql
CREATE INDEX recipients_membership ON message_recipients(membership_id, message_id);
```

| `sqlite_autoindex_message_recipients_1` | 是 | message_id, membership_id | 否 |

### 完整建表约束

```sql
CREATE TABLE message_recipients (
    message_id TEXT NOT NULL REFERENCES messages(message_id),
    membership_id TEXT NOT NULL REFERENCES conversation_memberships(membership_id),
    PRIMARY KEY(message_id, membership_id)
);
```


## `input_batch_messages`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `input_batch_id` | TEXT | 否 | — | 1 |
| `message_id` | TEXT | 否 | — | 2 |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `message_id` | `messages` | `message_id` | NO ACTION | NO ACTION |
| 1 | `input_batch_id` | `input_batches` | `input_batch_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_input_batch_messages_2` | 是 | input_batch_id, message_id | 否 |
| `sqlite_autoindex_input_batch_messages_1` | 是 | message_id | 否 |

### 完整建表约束

```sql
CREATE TABLE input_batch_messages (
    input_batch_id TEXT NOT NULL REFERENCES input_batches(input_batch_id),
    message_id TEXT NOT NULL UNIQUE REFERENCES messages(message_id),
    PRIMARY KEY(input_batch_id, message_id)
);
```


## `relation_evidence`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `evidence_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `observer_character_id` | TEXT | 否 | — | — |
| `target_kind` | TEXT | 否 | — | — |
| `target_id` | TEXT | 否 | — | — |
| `evidence_kind` | TEXT | 否 | — | — |
| `source_kind` | TEXT | 否 | — | — |
| `source_ref` | TEXT | 否 | — | — |
| `occurred_at_utc` | TEXT | 否 | — | — |
| `recorded_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `community_members` | `community_id` | NO ACTION | NO ACTION |
| 0 | `target_kind` | `community_members` | `actor_kind` | NO ACTION | NO ACTION |
| 0 | `target_id` | `community_members` | `actor_id` | NO ACTION | NO ACTION |
| 1 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 1 | `observer_character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `evidence_target` | 否 | observer_character_id, target_kind, target_id, occurred_at_utc | 否 |

```sql
CREATE INDEX evidence_target ON relation_evidence(observer_character_id, target_kind, target_id, occurred_at_utc);
```

| `sqlite_autoindex_relation_evidence_3` | 是 | community_id, observer_character_id, target_kind, target_id, evidence_id | 否 |
| `sqlite_autoindex_relation_evidence_2` | 是 | community_id, observer_character_id, target_kind, target_id, source_kind, source_ref | 否 |
| `sqlite_autoindex_relation_evidence_1` | 是 | evidence_id | 否 |

### 完整建表约束

```sql
CREATE TABLE relation_evidence (
    evidence_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, observer_character_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('player','character')), target_id TEXT NOT NULL,
    evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('interaction','support','conflict','commitment')),
    source_kind TEXT NOT NULL, source_ref TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL, recorded_at_utc TEXT NOT NULL CHECK(recorded_at_utc >= occurred_at_utc),
    FOREIGN KEY(community_id, observer_character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, target_kind, target_id) REFERENCES community_members(community_id, actor_kind, actor_id),
    UNIQUE(community_id, observer_character_id, target_kind, target_id, source_kind, source_ref),
    UNIQUE(community_id, observer_character_id, target_kind, target_id, evidence_id)
);
```


## `relationship_state`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `community_id` | TEXT | 否 | — | 1 |
| `observer_character_id` | TEXT | 否 | — | 2 |
| `target_kind` | TEXT | 否 | — | 3 |
| `target_id` | TEXT | 否 | — | 4 |
| `relationship_type` | TEXT | 否 | — | — |
| `affection` | REAL | 是 | — | — |
| `trust` | REAL | 是 | — | — |
| `attachment` | REAL | 是 | — | — |
| `friend_qualifying_evidence_id` | TEXT | 是 | — | — |
| `attitude_summary` | TEXT | 否 | '' | — |
| `attitude_source_refs_json` | TEXT | 否 | '[]' | — |
| `state_version` | INTEGER | 否 | 0 | — |
| `updated_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `relation_evidence` | `community_id` | NO ACTION | NO ACTION |
| 0 | `observer_character_id` | `relation_evidence` | `observer_character_id` | NO ACTION | NO ACTION |
| 0 | `target_kind` | `relation_evidence` | `target_kind` | NO ACTION | NO ACTION |
| 0 | `target_id` | `relation_evidence` | `target_id` | NO ACTION | NO ACTION |
| 0 | `friend_qualifying_evidence_id` | `relation_evidence` | `evidence_id` | NO ACTION | NO ACTION |
| 1 | `community_id` | `community_members` | `community_id` | NO ACTION | NO ACTION |
| 1 | `target_kind` | `community_members` | `actor_kind` | NO ACTION | NO ACTION |
| 1 | `target_id` | `community_members` | `actor_id` | NO ACTION | NO ACTION |
| 2 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 2 | `observer_character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_relationship_state_1` | 是 | community_id, observer_character_id, target_kind, target_id | 否 |

### 完整建表约束

```sql
CREATE TABLE relationship_state (
    community_id TEXT NOT NULL, observer_character_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('player','character')), target_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL CHECK(relationship_type IN ('stranger','acquaintance','friend')),
    affection REAL CHECK(affection BETWEEN 0 AND 100), trust REAL CHECK(trust BETWEEN 0 AND 100),
    attachment REAL CHECK(attachment BETWEEN 0 AND 100), friend_qualifying_evidence_id TEXT,
    attitude_summary TEXT NOT NULL DEFAULT '',
    attitude_source_refs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(attitude_source_refs_json) AND json_type(attitude_source_refs_json) = 'array'),
    state_version INTEGER NOT NULL DEFAULT 0 CHECK(state_version >= 0), updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(community_id, observer_character_id, target_kind, target_id),
    FOREIGN KEY(community_id, observer_character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, target_kind, target_id) REFERENCES community_members(community_id, actor_kind, actor_id),
    FOREIGN KEY(community_id, observer_character_id, target_kind, target_id, friend_qualifying_evidence_id)
        REFERENCES relation_evidence(community_id, observer_character_id, target_kind, target_id, evidence_id),
    CHECK((relationship_type = 'stranger' AND affection IS NULL AND trust IS NULL AND attachment IS NULL AND
          friend_qualifying_evidence_id IS NULL AND attitude_summary = '' AND json_array_length(attitude_source_refs_json) = 0) OR
          (relationship_type != 'stranger' AND affection IS NOT NULL AND trust IS NOT NULL AND attachment IS NOT NULL)),
    CHECK(relationship_type != 'friend' OR friend_qualifying_evidence_id IS NOT NULL),
    CHECK((attitude_summary = '' AND json_array_length(attitude_source_refs_json) = 0) OR
          (length(trim(attitude_summary)) > 0 AND json_array_length(attitude_source_refs_json) > 0))
);
```


## `memory_segments`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `segment_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | — |
| `conversation_id` | TEXT | 否 | — | — |
| `first_message_sequence` | INTEGER | 否 | — | — |
| `last_message_sequence` | INTEGER | 否 | — | — |
| `status` | TEXT | 否 | — | — |
| `source_version` | TEXT | 否 | — | — |
| `summary_text` | TEXT | 是 | — | — |
| `summary_version` | TEXT | 是 | — | — |
| `sealed_at_utc` | TEXT | 否 | — | — |
| `ingested_at_utc` | TEXT | 是 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `conversations` | `community_id` | NO ACTION | NO ACTION |
| 0 | `conversation_id` | `conversations` | `conversation_id` | NO ACTION | NO ACTION |
| 1 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 1 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `segments_pending` | 否 | status, sealed_at_utc, segment_id | 否 |

```sql
CREATE INDEX segments_pending ON memory_segments(status, sealed_at_utc, segment_id);
```

| `segments_order` | 否 | character_id, conversation_id, first_message_sequence | 否 |

```sql
CREATE INDEX segments_order ON memory_segments(character_id, conversation_id, first_message_sequence);
```

| `sqlite_autoindex_memory_segments_3` | 是 | character_id, conversation_id, segment_id | 否 |
| `sqlite_autoindex_memory_segments_2` | 是 | character_id, conversation_id, first_message_sequence, last_message_sequence | 否 |
| `sqlite_autoindex_memory_segments_1` | 是 | segment_id | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_segments (
    segment_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    first_message_sequence INTEGER NOT NULL CHECK(first_message_sequence >= 1),
    last_message_sequence INTEGER NOT NULL CHECK(last_message_sequence >= first_message_sequence),
    status TEXT NOT NULL CHECK(status IN ('sealed','ingested')), source_version TEXT NOT NULL,
    summary_text TEXT, summary_version TEXT, sealed_at_utc TEXT NOT NULL, ingested_at_utc TEXT,
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    UNIQUE(character_id, conversation_id, first_message_sequence, last_message_sequence),
    UNIQUE(character_id, conversation_id, segment_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    CHECK((status = 'sealed' AND ingested_at_utc IS NULL) OR (status = 'ingested' AND ingested_at_utc IS NOT NULL)),
    CHECK((summary_text IS NULL AND summary_version IS NULL) OR (summary_text IS NOT NULL AND summary_version IS NOT NULL))
);
```


## `memory_segment_sources`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `segment_id` | TEXT | 否 | — | 1 |
| `source_kind` | TEXT | 否 | — | 2 |
| `source_id` | TEXT | 否 | — | 3 |
| `source_version` | TEXT | 否 | — | — |
| `ordinal` | INTEGER | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `segment_id` | `memory_segments` | `segment_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_memory_segment_sources_2` | 是 | segment_id, ordinal | 否 |
| `sqlite_autoindex_memory_segment_sources_1` | 是 | segment_id, source_kind, source_id | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_segment_sources (
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought')), source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(segment_id, source_kind, source_id), UNIQUE(segment_id, ordinal)
);
```


## `memory_entries`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `memory_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | — |
| `memory_kind` | TEXT | 否 | — | — |
| `content` | TEXT | 否 | — | — |
| `confidence` | REAL | 否 | 1.0 | — |
| `salience` | REAL | 否 | 0.5 | — |
| `source_kind` | TEXT | 否 | — | — |
| `source_ref` | TEXT | 否 | — | — |
| `subject_kind` | TEXT | 否 | — | — |
| `subject_id` | TEXT | 否 | — | — |
| `visibility` | TEXT | 否 | — | — |
| `content_version` | TEXT | 否 | — | — |
| `occurred_at_utc` | TEXT | 是 | — | — |
| `recorded_at_utc` | TEXT | 否 | — | — |
| `expires_at_utc` | TEXT | 是 | — | — |
| `invalidated_at_utc` | TEXT | 是 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 0 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `memories_source` | 否 | character_id, source_kind, source_ref | 否 |

```sql
CREATE INDEX memories_source ON memory_entries(character_id, source_kind, source_ref);
```

| `memories_resident` | 否 | character_id, visibility, salience, recorded_at_utc | 是 |

```sql
CREATE INDEX memories_resident ON memory_entries(character_id, visibility, salience DESC, recorded_at_utc DESC) WHERE invalidated_at_utc IS NULL;
```

| `sqlite_autoindex_memory_entries_2` | 是 | character_id, memory_id | 否 |
| `sqlite_autoindex_memory_entries_1` | 是 | memory_id | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_entries (
    memory_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    memory_kind TEXT NOT NULL CHECK(memory_kind IN ('fact','event','preference','promise','thread','other')),
    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
    confidence REAL NOT NULL DEFAULT 1.0 CHECK(confidence BETWEEN 0 AND 1),
    salience REAL NOT NULL DEFAULT 0.5 CHECK(salience BETWEEN 0 AND 1),
    source_kind TEXT NOT NULL, source_ref TEXT NOT NULL, subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK(visibility IN ('resident','recallable','private')), content_version TEXT NOT NULL,
    occurred_at_utc TEXT, recorded_at_utc TEXT NOT NULL, expires_at_utc TEXT, invalidated_at_utc TEXT,
    UNIQUE(character_id, memory_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    CHECK(expires_at_utc IS NULL OR expires_at_utc > recorded_at_utc),
    CHECK(invalidated_at_utc IS NULL OR invalidated_at_utc >= recorded_at_utc)
);
```


## `thoughts`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `thought_id` | TEXT | 否 | — | 1 |
| `result_id` | TEXT | 否 | — | — |
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | — |
| `conversation_id` | TEXT | 否 | — | — |
| `game_day` | TEXT | 否 | — | — |
| `content` | TEXT | 是 | — | — |
| `content_version` | TEXT | 否 | — | — |
| `segment_id` | TEXT | 是 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `content_removed_at_utc` | TEXT | 是 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `character_id` | `memory_segments` | `character_id` | NO ACTION | NO ACTION |
| 0 | `conversation_id` | `memory_segments` | `conversation_id` | NO ACTION | NO ACTION |
| 0 | `segment_id` | `memory_segments` | `segment_id` | NO ACTION | NO ACTION |
| 1 | `community_id` | `conversations` | `community_id` | NO ACTION | NO ACTION |
| 1 | `conversation_id` | `conversations` | `conversation_id` | NO ACTION | NO ACTION |
| 2 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 2 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |
| 3 | `result_id` | `conversation_results` | `result_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `thoughts_segment` | 否 | segment_id | 否 |

```sql
CREATE INDEX thoughts_segment ON thoughts(segment_id);
```

| `thoughts_day` | 否 | character_id, game_day, created_at_utc | 否 |

```sql
CREATE INDEX thoughts_day ON thoughts(character_id, game_day, created_at_utc);
```

| `sqlite_autoindex_thoughts_2` | 是 | result_id | 否 |
| `sqlite_autoindex_thoughts_1` | 是 | thought_id | 否 |

### 完整建表约束

```sql
CREATE TABLE thoughts (
    thought_id TEXT PRIMARY KEY NOT NULL, result_id TEXT NOT NULL UNIQUE REFERENCES conversation_results(result_id),
    community_id TEXT NOT NULL, character_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    game_day TEXT NOT NULL CHECK(date(game_day) IS NOT NULL AND date(game_day) = game_day),
    content TEXT, content_version TEXT NOT NULL, segment_id TEXT,
    created_at_utc TEXT NOT NULL, content_removed_at_utc TEXT,
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    FOREIGN KEY(character_id, conversation_id, segment_id) REFERENCES memory_segments(character_id, conversation_id, segment_id),
    CHECK((content IS NOT NULL AND length(trim(content)) > 0 AND content_removed_at_utc IS NULL) OR
          (content IS NULL AND content_removed_at_utc IS NOT NULL AND content_removed_at_utc >= created_at_utc))
);
```


## `memory_source_coverage`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | 1 |
| `owner_kind` | TEXT | 否 | — | 2 |
| `owner_id` | TEXT | 否 | — | 3 |
| `source_kind` | TEXT | 否 | — | 4 |
| `source_id` | TEXT | 否 | — | 5 |
| `source_version` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 0 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `coverage_source` | 否 | character_id, source_kind, source_id | 否 |

```sql
CREATE INDEX coverage_source ON memory_source_coverage(character_id, source_kind, source_id);
```

| `sqlite_autoindex_memory_source_coverage_1` | 是 | character_id, owner_kind, owner_id, source_kind, source_id | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_source_coverage (
    community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    owner_kind TEXT NOT NULL CHECK(owner_kind IN ('segment_summary','diary')), owner_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought','segment_summary')), source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(character_id, owner_kind, owner_id, source_kind, source_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id)
);
```


## `memory_summary_batches`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `batch_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | — |
| `conversation_id` | TEXT | 否 | — | — |
| `source_version` | TEXT | 否 | — | — |
| `previous_digest_id` | TEXT | 是 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `conversations` | `community_id` | NO ACTION | NO ACTION |
| 0 | `conversation_id` | `conversations` | `conversation_id` | NO ACTION | NO ACTION |
| 1 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 1 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |
| 2 | `previous_digest_id` | `conversation_digests` | `digest_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_memory_summary_batches_2` | 是 | character_id, conversation_id, source_version | 否 |
| `sqlite_autoindex_memory_summary_batches_1` | 是 | batch_id | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_summary_batches (
    batch_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    source_version TEXT NOT NULL, previous_digest_id TEXT REFERENCES conversation_digests(digest_id), created_at_utc TEXT NOT NULL,
    UNIQUE(character_id, conversation_id, source_version),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id)
);
```


## `memory_summary_batch_items`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `batch_id` | TEXT | 否 | — | 1 |
| `ordinal` | INTEGER | 否 | — | 2 |
| `segment_id` | TEXT | 否 | — | — |
| `summary_version` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `segment_id` | `memory_segments` | `segment_id` | NO ACTION | NO ACTION |
| 1 | `batch_id` | `memory_summary_batches` | `batch_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_memory_summary_batch_items_2` | 是 | batch_id, segment_id | 否 |
| `sqlite_autoindex_memory_summary_batch_items_1` | 是 | batch_id, ordinal | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_summary_batch_items (
    batch_id TEXT NOT NULL REFERENCES memory_summary_batches(batch_id), ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id), summary_version TEXT NOT NULL,
    PRIMARY KEY(batch_id, ordinal), UNIQUE(batch_id, segment_id)
);
```


## `conversation_digests`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `digest_id` | TEXT | 否 | — | 1 |
| `batch_id` | TEXT | 否 | — | — |
| `content` | TEXT | 否 | — | — |
| `content_version` | TEXT | 否 | — | — |
| `covers_through_sequence` | INTEGER | 否 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `batch_id` | `memory_summary_batches` | `batch_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_conversation_digests_2` | 是 | batch_id | 否 |
| `sqlite_autoindex_conversation_digests_1` | 是 | digest_id | 否 |

### 完整建表约束

```sql
CREATE TABLE conversation_digests (
    digest_id TEXT PRIMARY KEY NOT NULL, batch_id TEXT NOT NULL UNIQUE REFERENCES memory_summary_batches(batch_id),
    content TEXT NOT NULL CHECK(length(trim(content)) > 0), content_version TEXT NOT NULL,
    covers_through_sequence INTEGER NOT NULL CHECK(covers_through_sequence >= 1), created_at_utc TEXT NOT NULL
);
```


## `memory_organization_consumption`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `segment_id` | TEXT | 否 | — | 1 |
| `summary_version` | TEXT | 否 | — | 2 |
| `batch_id` | TEXT | 否 | — | — |
| `outcome` | TEXT | 否 | — | — |
| `consumed_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `batch_id` | `memory_summary_batches` | `batch_id` | NO ACTION | NO ACTION |
| 1 | `segment_id` | `memory_segments` | `segment_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_memory_organization_consumption_1` | 是 | segment_id, summary_version | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_organization_consumption (
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id), summary_version TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES memory_summary_batches(batch_id),
    outcome TEXT NOT NULL CHECK(outcome IN ('completed','no_op')), consumed_at_utc TEXT NOT NULL,
    PRIMARY KEY(segment_id, summary_version)
);
```


## `diary_entries`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `diary_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | — |
| `game_day` | TEXT | 否 | — | — |
| `content` | TEXT | 否 | — | — |
| `content_version` | TEXT | 否 | — | — |
| `source_window_kind` | TEXT | 否 | — | — |
| `source_window_ref` | TEXT | 否 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 0 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_diary_entries_2` | 是 | character_id, game_day | 否 |
| `sqlite_autoindex_diary_entries_1` | 是 | diary_id | 否 |

### 完整建表约束

```sql
CREATE TABLE diary_entries (
    diary_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    game_day TEXT NOT NULL CHECK(date(game_day) IS NOT NULL AND date(game_day) = game_day),
    content TEXT NOT NULL, content_version TEXT NOT NULL, source_window_kind TEXT NOT NULL, source_window_ref TEXT NOT NULL,
    created_at_utc TEXT NOT NULL, UNIQUE(character_id, game_day),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id)
);
```


## `memory_views`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | 1 |
| `view_kind` | TEXT | 否 | — | 2 |
| `content` | TEXT | 否 | — | — |
| `content_version` | TEXT | 否 | — | — |
| `source_refs_json` | TEXT | 否 | — | — |
| `source_snapshot_version` | TEXT | 是 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 0 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_memory_views_1` | 是 | character_id, view_kind | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_views (
    community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    view_kind TEXT NOT NULL CHECK(view_kind IN ('core_memory','state_summary')),
    content TEXT NOT NULL, content_version TEXT NOT NULL,
    source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json)), source_snapshot_version TEXT, updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(character_id, view_kind),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id)
);
```


## `memory_entities`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `entity_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | — |
| `entity_kind` | TEXT | 否 | — | — |
| `canonical_name` | TEXT | 否 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |
| `invalidated_at_utc` | TEXT | 是 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 0 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_memory_entities_2` | 是 | character_id, entity_id | 否 |
| `sqlite_autoindex_memory_entities_1` | 是 | entity_id | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_entities (
    entity_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    entity_kind TEXT NOT NULL, canonical_name TEXT NOT NULL, created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL, invalidated_at_utc TEXT,
    UNIQUE(character_id, entity_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id)
);
```


## `memory_entity_aliases`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `alias_id` | TEXT | 否 | — | 1 |
| `character_id` | TEXT | 否 | — | — |
| `entity_id` | TEXT | 否 | — | — |
| `alias_text` | TEXT | 否 | — | — |
| `normalized_alias` | TEXT | 否 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `invalidated_at_utc` | TEXT | 是 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `character_id` | `memory_entities` | `character_id` | NO ACTION | NO ACTION |
| 0 | `entity_id` | `memory_entities` | `entity_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `aliases_active` | 是 | character_id, normalized_alias | 是 |

```sql
CREATE UNIQUE INDEX aliases_active ON memory_entity_aliases(character_id, normalized_alias) WHERE invalidated_at_utc IS NULL;
```

| `sqlite_autoindex_memory_entity_aliases_1` | 是 | alias_id | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_entity_aliases (
    alias_id TEXT PRIMARY KEY NOT NULL, character_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    alias_text TEXT NOT NULL, normalized_alias TEXT NOT NULL, created_at_utc TEXT NOT NULL, invalidated_at_utc TEXT,
    FOREIGN KEY(character_id, entity_id) REFERENCES memory_entities(character_id, entity_id)
);
```


## `memory_entry_entities`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `character_id` | TEXT | 否 | — | 1 |
| `memory_id` | TEXT | 否 | — | 2 |
| `entity_id` | TEXT | 否 | — | 3 |
| `role` | TEXT | 否 | — | 4 |
| `created_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `character_id` | `memory_entities` | `character_id` | NO ACTION | NO ACTION |
| 0 | `entity_id` | `memory_entities` | `entity_id` | NO ACTION | NO ACTION |
| 1 | `character_id` | `memory_entries` | `character_id` | NO ACTION | NO ACTION |
| 1 | `memory_id` | `memory_entries` | `memory_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `entries_entity` | 否 | character_id, entity_id, memory_id | 否 |

```sql
CREATE INDEX entries_entity ON memory_entry_entities(character_id, entity_id, memory_id);
```

| `sqlite_autoindex_memory_entry_entities_1` | 是 | character_id, memory_id, entity_id, role | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_entry_entities (
    character_id TEXT NOT NULL, memory_id TEXT NOT NULL, entity_id TEXT NOT NULL, role TEXT NOT NULL, created_at_utc TEXT NOT NULL,
    PRIMARY KEY(character_id, memory_id, entity_id, role),
    FOREIGN KEY(character_id, memory_id) REFERENCES memory_entries(character_id, memory_id),
    FOREIGN KEY(character_id, entity_id) REFERENCES memory_entities(character_id, entity_id)
);
```


## `memory_edges`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `edge_id` | TEXT | 否 | — | 1 |
| `character_id` | TEXT | 否 | — | — |
| `from_entity_id` | TEXT | 否 | — | — |
| `to_entity_id` | TEXT | 否 | — | — |
| `edge_kind` | TEXT | 否 | — | — |
| `confidence` | REAL | 否 | 1.0 | — |
| `source_memory_id` | TEXT | 是 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `invalidated_at_utc` | TEXT | 是 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `character_id` | `memory_entries` | `character_id` | NO ACTION | NO ACTION |
| 0 | `source_memory_id` | `memory_entries` | `memory_id` | NO ACTION | NO ACTION |
| 1 | `character_id` | `memory_entities` | `character_id` | NO ACTION | NO ACTION |
| 1 | `to_entity_id` | `memory_entities` | `entity_id` | NO ACTION | NO ACTION |
| 2 | `character_id` | `memory_entities` | `character_id` | NO ACTION | NO ACTION |
| 2 | `from_entity_id` | `memory_entities` | `entity_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `edges_to` | 否 | character_id, to_entity_id | 是 |

```sql
CREATE INDEX edges_to ON memory_edges(character_id, to_entity_id) WHERE invalidated_at_utc IS NULL;
```

| `edges_from` | 否 | character_id, from_entity_id | 是 |

```sql
CREATE INDEX edges_from ON memory_edges(character_id, from_entity_id) WHERE invalidated_at_utc IS NULL;
```

| `edges_without_source` | 是 | character_id, from_entity_id, to_entity_id, edge_kind | 是 |

```sql
CREATE UNIQUE INDEX edges_without_source ON memory_edges(character_id, from_entity_id, to_entity_id, edge_kind) WHERE source_memory_id IS NULL;
```

| `sqlite_autoindex_memory_edges_2` | 是 | character_id, from_entity_id, to_entity_id, edge_kind, source_memory_id | 否 |
| `sqlite_autoindex_memory_edges_1` | 是 | edge_id | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_edges (
    edge_id TEXT PRIMARY KEY NOT NULL, character_id TEXT NOT NULL, from_entity_id TEXT NOT NULL, to_entity_id TEXT NOT NULL,
    edge_kind TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 1.0 CHECK(confidence BETWEEN 0 AND 1), source_memory_id TEXT,
    created_at_utc TEXT NOT NULL, invalidated_at_utc TEXT,
    FOREIGN KEY(character_id, from_entity_id) REFERENCES memory_entities(character_id, entity_id),
    FOREIGN KEY(character_id, to_entity_id) REFERENCES memory_entities(character_id, entity_id),
    FOREIGN KEY(character_id, source_memory_id) REFERENCES memory_entries(character_id, memory_id),
    UNIQUE(character_id, from_entity_id, to_entity_id, edge_kind, source_memory_id)
);
```


## `memory_search_documents`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `document_id` | INTEGER | 是 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | — |
| `conversation_id` | TEXT | 是 | — | — |
| `source_kind` | TEXT | 否 | — | — |
| `source_id` | TEXT | 否 | — | — |
| `source_version` | TEXT | 否 | — | — |
| `occurred_at_utc` | TEXT | 是 | — | — |
| `searchable` | INTEGER | 否 | 1 | — |
| `updated_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `conversations` | `community_id` | NO ACTION | NO ACTION |
| 0 | `conversation_id` | `conversations` | `conversation_id` | NO ACTION | NO ACTION |
| 1 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 1 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `search_scope` | 否 | character_id, searchable, source_kind | 否 |

```sql
CREATE INDEX search_scope ON memory_search_documents(character_id, searchable, source_kind);
```

| `sqlite_autoindex_memory_search_documents_1` | 是 | character_id, source_kind, source_id | 否 |

### 完整建表约束

```sql
CREATE TABLE memory_search_documents (
    document_id INTEGER PRIMARY KEY, community_id TEXT NOT NULL, character_id TEXT NOT NULL, conversation_id TEXT,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('memory_entry','message')), source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    occurred_at_utc TEXT, searchable INTEGER NOT NULL DEFAULT 1 CHECK(searchable IN (0,1)), updated_at_utc TEXT NOT NULL,
    UNIQUE(character_id, source_kind, source_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id)
);
```


## `memory_search_fts`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `tokenized_text` |  | 是 | — | — |
| `display_text` |  | 是 | — | — |

### 完整建表约束

```sql
CREATE VIRTUAL TABLE memory_search_fts USING fts5(tokenized_text, display_text UNINDEXED);
```


## `reflection_graph_runs`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `graph_run_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | — |
| `graph_kind` | TEXT | 否 | — | — |
| `graph_version` | TEXT | 否 | — | — |
| `context_snapshot_id` | TEXT | 否 | — | — |
| `snapshot_schema_version` | INTEGER | 否 | 1 | — |
| `snapshot_json` | TEXT | 否 | — | — |
| `snapshot_fingerprint` | TEXT | 否 | — | — |
| `source_scope_json` | TEXT | 否 | — | — |
| `source_scope_fingerprint` | TEXT | 否 | — | — |
| `topology_node_keys_json` | TEXT | 否 | — | — |
| `required_node_keys_json` | TEXT | 否 | — | — |
| `registered_node_keys_json` | TEXT | 否 | — | — |
| `status` | TEXT | 否 | — | — |
| `execution_generation` | INTEGER | 否 | 0 | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |
| `started_at_utc` | TEXT | 是 | — | — |
| `completed_at_utc` | TEXT | 是 | — | — |
| `last_error_code` | TEXT | 是 | — | — |
| `trace_id` | TEXT | 是 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `character_instances` | `community_id` | NO ACTION | NO ACTION |
| 0 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `graphs_recovery` | 否 | status, updated_at_utc, graph_run_id | 否 |

```sql
CREATE INDEX graphs_recovery ON reflection_graph_runs(status, updated_at_utc, graph_run_id);
```

| `sqlite_autoindex_reflection_graph_runs_2` | 是 | character_id, graph_kind, graph_version, context_snapshot_id, source_scope_fingerprint | 否 |
| `sqlite_autoindex_reflection_graph_runs_1` | 是 | graph_run_id | 否 |

### 完整建表约束

```sql
CREATE TABLE reflection_graph_runs (
    graph_run_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    graph_kind TEXT NOT NULL, graph_version TEXT NOT NULL, context_snapshot_id TEXT NOT NULL,
    snapshot_schema_version INTEGER NOT NULL DEFAULT 1 CHECK(snapshot_schema_version = 1),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)), snapshot_fingerprint TEXT NOT NULL,
    source_scope_json TEXT NOT NULL CHECK(json_valid(source_scope_json)), source_scope_fingerprint TEXT NOT NULL,
    topology_node_keys_json TEXT NOT NULL CHECK(json_valid(topology_node_keys_json)),
    required_node_keys_json TEXT NOT NULL CHECK(json_valid(required_node_keys_json)),
    registered_node_keys_json TEXT NOT NULL CHECK(json_valid(registered_node_keys_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','running','retry_wait','completed','partial','failed','cancelled')),
    execution_generation INTEGER NOT NULL DEFAULT 0 CHECK(execution_generation >= 0),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL, started_at_utc TEXT, completed_at_utc TEXT,
    last_error_code TEXT, trace_id TEXT,
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    UNIQUE(character_id, graph_kind, graph_version, context_snapshot_id, source_scope_fingerprint),
    CHECK((status IN ('completed','partial','failed','cancelled') AND completed_at_utc IS NOT NULL) OR
          (status IN ('pending','running','retry_wait') AND completed_at_utc IS NULL))
);
```


## `reflection_node_tasks`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `node_task_id` | TEXT | 否 | — | 1 |
| `graph_run_id` | TEXT | 否 | — | — |
| `node_key` | TEXT | 否 | — | — |
| `node_kind` | TEXT | 否 | — | — |
| `dependency_keys_json` | TEXT | 否 | — | — |
| `activated` | INTEGER | 否 | — | — |
| `node_input_fingerprint` | TEXT | 否 | — | — |
| `input_artifact_refs_json` | TEXT | 否 | — | — |
| `output_contract_kind` | TEXT | 否 | — | — |
| `output_contract_version` | TEXT | 否 | — | — |
| `status` | TEXT | 否 | — | — |
| `attempt_count` | INTEGER | 否 | 0 | — |
| `lease_generation` | INTEGER | 否 | 0 | — |
| `available_at_utc` | TEXT | 否 | — | — |
| `lease_owner` | TEXT | 是 | — | — |
| `lease_until_utc` | TEXT | 是 | — | — |
| `last_error_code` | TEXT | 是 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `graph_run_id` | `reflection_graph_runs` | `graph_run_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `nodes_graph` | 否 | graph_run_id, status, activated, available_at_utc | 否 |

```sql
CREATE INDEX nodes_graph ON reflection_node_tasks(graph_run_id, status, activated, available_at_utc);
```

| `nodes_claim` | 否 | status, available_at_utc, created_at_utc | 否 |

```sql
CREATE INDEX nodes_claim ON reflection_node_tasks(status, available_at_utc, created_at_utc);
```

| `sqlite_autoindex_reflection_node_tasks_3` | 是 | graph_run_id, node_task_id | 否 |
| `sqlite_autoindex_reflection_node_tasks_2` | 是 | graph_run_id, node_key | 否 |
| `sqlite_autoindex_reflection_node_tasks_1` | 是 | node_task_id | 否 |

### 完整建表约束

```sql
CREATE TABLE reflection_node_tasks (
    node_task_id TEXT PRIMARY KEY NOT NULL, graph_run_id TEXT NOT NULL REFERENCES reflection_graph_runs(graph_run_id),
    node_key TEXT NOT NULL, node_kind TEXT NOT NULL,
    dependency_keys_json TEXT NOT NULL CHECK(json_valid(dependency_keys_json)), activated INTEGER NOT NULL CHECK(activated IN (0,1)),
    node_input_fingerprint TEXT NOT NULL, input_artifact_refs_json TEXT NOT NULL CHECK(json_valid(input_artifact_refs_json)),
    output_contract_kind TEXT NOT NULL, output_contract_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','processing','retry_wait','skipped','completed','failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0), lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0),
    available_at_utc TEXT NOT NULL, lease_owner TEXT, lease_until_utc TEXT, last_error_code TEXT,
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    UNIQUE(graph_run_id, node_key), UNIQUE(graph_run_id, node_task_id),
    CHECK((status = 'processing' AND lease_owner IS NOT NULL AND lease_until_utc IS NOT NULL) OR
          (status != 'processing' AND lease_owner IS NULL AND lease_until_utc IS NULL))
);
```


## `reflection_artifacts`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `artifact_id` | TEXT | 否 | — | 1 |
| `graph_run_id` | TEXT | 否 | — | — |
| `node_task_id` | TEXT | 否 | — | — |
| `invocation_id` | TEXT | 是 | — | — |
| `attempt` | INTEGER | 否 | — | — |
| `node_input_fingerprint` | TEXT | 否 | — | — |
| `output_contract_kind` | TEXT | 否 | — | — |
| `output_contract_version` | TEXT | 否 | — | — |
| `payload_json` | TEXT | 否 | — | — |
| `content_fingerprint` | TEXT | 否 | — | — |
| `evidence_refs_json` | TEXT | 否 | — | — |
| `audit_json` | TEXT | 否 | '{}' | — |
| `created_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `graph_run_id` | `reflection_node_tasks` | `graph_run_id` | NO ACTION | NO ACTION |
| 0 | `node_task_id` | `reflection_node_tasks` | `node_task_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `artifacts_graph` | 否 | graph_run_id, created_at_utc, artifact_id | 否 |

```sql
CREATE INDEX artifacts_graph ON reflection_artifacts(graph_run_id, created_at_utc, artifact_id);
```

| `sqlite_autoindex_reflection_artifacts_2` | 是 | node_task_id, attempt | 否 |
| `sqlite_autoindex_reflection_artifacts_1` | 是 | artifact_id | 否 |

### 完整建表约束

```sql
CREATE TABLE reflection_artifacts (
    artifact_id TEXT PRIMARY KEY NOT NULL, graph_run_id TEXT NOT NULL, node_task_id TEXT NOT NULL, invocation_id TEXT,
    attempt INTEGER NOT NULL CHECK(attempt >= 1), node_input_fingerprint TEXT NOT NULL,
    output_contract_kind TEXT NOT NULL, output_contract_version TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), content_fingerprint TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL CHECK(json_valid(evidence_refs_json)), audit_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(audit_json)),
    created_at_utc TEXT NOT NULL, UNIQUE(node_task_id, attempt),
    FOREIGN KEY(graph_run_id, node_task_id) REFERENCES reflection_node_tasks(graph_run_id, node_task_id)
);
```


## `reflection_graph_results`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `result_id` | TEXT | 否 | — | 1 |
| `graph_run_id` | TEXT | 否 | — | — |
| `aggregate_fingerprint` | TEXT | 否 | — | — |
| `payload_json` | TEXT | 否 | — | — |
| `status` | TEXT | 否 | — | — |
| `decision_code` | TEXT | 是 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `decided_at_utc` | TEXT | 是 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `graph_run_id` | `reflection_graph_runs` | `graph_run_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_reflection_graph_results_2` | 是 | graph_run_id | 否 |
| `sqlite_autoindex_reflection_graph_results_1` | 是 | result_id | 否 |

### 完整建表约束

```sql
CREATE TABLE reflection_graph_results (
    result_id TEXT PRIMARY KEY NOT NULL, graph_run_id TEXT NOT NULL UNIQUE REFERENCES reflection_graph_runs(graph_run_id),
    aggregate_fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','expired','skipped')),
    decision_code TEXT, created_at_utc TEXT NOT NULL, decided_at_utc TEXT,
    CHECK((status = 'pending' AND decision_code IS NULL AND decided_at_utc IS NULL) OR
          (status != 'pending' AND decision_code IS NOT NULL AND decided_at_utc IS NOT NULL))
);
```


## `trace_outbox`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `trace_id` | TEXT | 否 | — | 1 |
| `correlation_id` | TEXT | 否 | — | — |
| `kind` | TEXT | 否 | — | — |
| `entity_type` | TEXT | 否 | — | — |
| `entity_id` | TEXT | 否 | — | — |
| `payload_json` | TEXT | 否 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `status` | TEXT | 否 | 'pending' | — |
| `attempt_count` | INTEGER | 否 | 0 | — |
| `available_at_utc` | TEXT | 否 | — | — |
| `lease_owner` | TEXT | 是 | — | — |
| `lease_until_utc` | TEXT | 是 | — | — |
| `last_error_code` | TEXT | 是 | — | — |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `outbox_claim` | 否 | status, available_at_utc, created_at_utc | 否 |

```sql
CREATE INDEX outbox_claim ON trace_outbox(status, available_at_utc, created_at_utc);
```

| `sqlite_autoindex_trace_outbox_1` | 是 | trace_id | 否 |

### 完整建表约束

```sql
CREATE TABLE trace_outbox (
    trace_id TEXT PRIMARY KEY NOT NULL, correlation_id TEXT NOT NULL, kind TEXT NOT NULL,
    entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), created_at_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0), available_at_utc TEXT NOT NULL,
    lease_owner TEXT, lease_until_utc TEXT, last_error_code TEXT,
    CHECK((status = 'processing' AND lease_owner IS NOT NULL AND lease_until_utc IS NOT NULL) OR
          (status != 'processing' AND lease_owner IS NULL AND lease_until_utc IS NULL))
);
```


## `traces`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `trace_id` | TEXT | 否 | — | 1 |
| `correlation_id` | TEXT | 否 | — | — |
| `kind` | TEXT | 否 | — | — |
| `entity_type` | TEXT | 否 | — | — |
| `entity_id` | TEXT | 否 | — | — |
| `payload_json` | TEXT | 否 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `traces_correlation` | 否 | correlation_id, created_at_utc, trace_id | 否 |

```sql
CREATE INDEX traces_correlation ON traces(correlation_id, created_at_utc, trace_id);
```

| `sqlite_autoindex_traces_1` | 是 | trace_id | 否 |

### 完整建表约束

```sql
CREATE TABLE traces (
    trace_id TEXT PRIMARY KEY NOT NULL, correlation_id TEXT NOT NULL, kind TEXT NOT NULL,
    entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), created_at_utc TEXT NOT NULL
);
```


## `social_turns`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `social_turn_id` | TEXT | 否 | — | 1 |
| `community_id` | TEXT | 否 | — | — |
| `conversation_id` | TEXT | 否 | — | — |
| `audience_json` | TEXT | 否 | — | — |
| `visibility` | TEXT | 否 | — | — |
| `observation_max_sequence` | INTEGER | 否 | — | — |
| `membership_version` | INTEGER | 否 | — | — |
| `status` | TEXT | 否 | — | — |
| `completion_json` | TEXT | 是 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |
| `completed_at_utc` | TEXT | 是 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `community_id` | `conversations` | `community_id` | NO ACTION | NO ACTION |
| 0 | `conversation_id` | `conversations` | `conversation_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `turns_running` | 是 | conversation_id | 是 |

```sql
CREATE UNIQUE INDEX turns_running ON social_turns(conversation_id) WHERE status = 'running';
```

| `sqlite_autoindex_social_turns_2` | 是 | community_id, conversation_id, social_turn_id | 否 |
| `sqlite_autoindex_social_turns_1` | 是 | social_turn_id | 否 |

### 完整建表约束

```sql
CREATE TABLE "social_turns" (
    social_turn_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    audience_json TEXT NOT NULL CHECK(json_valid(audience_json) AND json_type(audience_json) = 'array'),
    visibility TEXT NOT NULL CHECK(visibility IN ('conversation','recipients')),
    observation_max_sequence INTEGER NOT NULL CHECK(observation_max_sequence >= 0),
    membership_version INTEGER NOT NULL CHECK(membership_version >= 0),
    status TEXT NOT NULL CHECK(status IN ('running','completed','cancelled')),
    completion_json TEXT CHECK(completion_json IS NULL OR json_valid(completion_json)),
    created_at_utc TEXT NOT NULL, completed_at_utc TEXT,
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    UNIQUE(community_id, conversation_id, social_turn_id),
    CHECK((status IN ('completed','cancelled') AND completed_at_utc IS NOT NULL AND completion_json IS NOT NULL)
       OR (status = 'running' AND completed_at_utc IS NULL AND completion_json IS NULL))
);
```


## `task_execution_events`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `event_id` | INTEGER | 是 | — | 1 |
| `event_kind` | TEXT | 否 | — | — |
| `task_kind` | TEXT | 否 | — | — |
| `task_id` | TEXT | 否 | — | — |
| `attempt` | INTEGER | 否 | — | — |
| `lease_generation` | INTEGER | 否 | — | — |
| `community_id` | TEXT | 否 | — | — |
| `character_id` | TEXT | 否 | — | — |
| `graph_run_id` | TEXT | 是 | — | — |
| `graph_execution_generation` | INTEGER | 是 | — | — |
| `invocation_id` | TEXT | 是 | — | — |
| `trace_id` | TEXT | 否 | — | — |
| `recorded_at_utc` | TEXT | 否 | — | — |
| `payload_json` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `character_id` | `character_instances` | `character_id` | NO ACTION | NO ACTION |
| 1 | `community_id` | `communities` | `community_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `idx_execution_events_graph` | 否 | graph_run_id, event_id | 否 |

```sql
CREATE INDEX idx_execution_events_graph ON task_execution_events(graph_run_id,event_id);
```

| `idx_execution_events_task` | 否 | task_kind, task_id, event_id | 否 |

```sql
CREATE INDEX idx_execution_events_task ON task_execution_events(task_kind,task_id,event_id);
```


### 完整建表约束

```sql
CREATE TABLE task_execution_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_kind TEXT NOT NULL,
    task_kind TEXT NOT NULL,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK(attempt >= 0),
    lease_generation INTEGER NOT NULL CHECK(lease_generation >= 0),
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    graph_run_id TEXT,
    graph_execution_generation INTEGER,
    invocation_id TEXT,
    trace_id TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
);
```


## `conversation_read_positions`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `player_id` | TEXT | 否 | — | 1 |
| `conversation_id` | TEXT | 否 | — | 2 |
| `last_read_sequence` | INTEGER | 否 | — | — |
| `updated_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `conversation_id` | `conversations` | `conversation_id` | NO ACTION | NO ACTION |
| 1 | `player_id` | `players` | `player_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `sqlite_autoindex_conversation_read_positions_1` | 是 | player_id, conversation_id | 否 |

### 完整建表约束

```sql
CREATE TABLE conversation_read_positions (
    player_id TEXT NOT NULL REFERENCES players(player_id),
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    last_read_sequence INTEGER NOT NULL CHECK (last_read_sequence >= 0),
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (player_id, conversation_id)
);
```


## `conversation_membership_operations`

| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |
|---|---|---|---|---|
| `operation_scope` | TEXT | 否 | — | 1 |
| `client_operation_id` | TEXT | 否 | — | 2 |
| `conversation_id` | TEXT | 否 | — | — |
| `request_json` | TEXT | 否 | — | — |
| `result_json` | TEXT | 否 | — | — |
| `created_at_utc` | TEXT | 否 | — | — |

### 外键

| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |
|---|---|---|---|---|---|
| 0 | `conversation_id` | `conversations` | `conversation_id` | NO ACTION | NO ACTION |

### 索引与唯一键

| 名称 | 唯一 | 字段顺序 | 部分索引 |
|---|---|---|---|
| `idx_membership_operations_conversation` | 否 | conversation_id | 否 |

```sql
CREATE INDEX idx_membership_operations_conversation
ON conversation_membership_operations(conversation_id);
```

| `sqlite_autoindex_conversation_membership_operations_1` | 是 | operation_scope, client_operation_id | 否 |

### 完整建表约束

```sql
CREATE TABLE conversation_membership_operations (
    operation_scope TEXT NOT NULL,
    client_operation_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (operation_scope, client_operation_id)
);
```
