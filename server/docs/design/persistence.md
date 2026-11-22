# 持久化、事务与迁移

SQLite 保存权威业务状态。API（接口）处理请求和协议，运行编排层控制调度与事务，领域服务决定业务规则，所属存储负责查询和写入。日志、追踪、模型输出及检索索引不能代替正式业务记录。

## 1. 数据归属

先按正在了解的功能选择模块，再阅读对应设计和表。“核心表”保存模块的主要对象；辅助表保存成员与受众、来源对应、处理位置或执行过程。下表列出代表，完整字段、约束和当前结构版本见[数据库参考](../reference/database-schema.md)。

| 模块与职责 | 先看的核心表 | 相关辅助表举例 | 维护者与详细设计 |
|---|---|---|---|
| 社群与玩家：身份、世界状态和成员 | `players`、`communities` | `community_members` | 社群服务；[身份与社群](identity-and-communities.md) |
| 人物创作：作者草稿与固定人物资料 | `character_authoring_drafts`、`custom_character_blueprints` | `character_authoring_candidates` | 人物创作服务；[创作设计](custom-character-authoring.md) |
| 角色：独立实例、状态和关系 | `character_instances`、`character_state_entries`、`relationship_state` | `relation_evidence`、`character_state_sources` | 角色服务；[状态与关系](character-state-and-relationships.md) |
| 会话：交流空间与正式消息 | `conversations`、`messages` | `conversation_memberships`、`message_recipients`、`message_mentions` | 会话服务；[会话设计](conversation-and-social.md) |
| 多人回应：输入收集、回应安排与任务结果 | `input_batches`、`social_turns`、`conversation_tasks`、`conversation_results` | `input_batch_messages`、`participation_decisions`、`social_observations` | 社交与会话运行层；[回应安排](conversation-and-social.md) |
| 记忆：私人内心、摘要、长期事实与认知 | `thoughts`、`memory_segments`、`memory_facts`、`memory_cognitions`、`memory_views` | `memory_segment_sources`、`memory_fact_sources`、`memory_source_coverage`、`memory_continuity_consumption` | 记忆服务及审核提交入口；[记忆设计](memory.md) |
| 游戏经历：参与边界、阶段材料与整局回忆 | `memory_activity_episodes` | `memory_activity_event_refs`，以及段和摘要批次的参与关联 | 记忆服务；[游戏经历](activity-memory.md) |
| 反思执行：整理任务、阶段产物与恢复 | `reflection_graph_runs`、`reflection_node_tasks` | `reflection_artifacts`、`reflection_graph_results`、`reflection_draft_steps` | 反思运行层；[执行模型](reflection/execution-model.md) |
| 游戏：对局、席位、实际参与和正式事件 | `game_games`、`game_participations`、`game_events` | `game_event_audiences`、`game_action_receipts`、`community_games` | 游戏服务及社群侧参与服务；[游戏与局内决策](#11-游戏与局内决策) |
| Activity（角色活动）：行动与回应、结果、输入及局内意图 | `activity_tasks`、`activity_results`、`activity_inputs`、`activity_working_memory` | `activity_task_sources`、`activity_observation_progress`、`activity_persona_projections` | 活动执行与上下文服务；[角色行动](activity-actions.md)、[局内协调](activity-coordination.md)、[活动输入](activity-context.md) |
| 图片：图像资产与生成任务 | `image_assets`、`image_generations` | `image_asset_files`、`image_asset_references` | 图像服务；[图像资产](image-assets.md) |
| 检索：从正式来源建立可重建的索引 | `memory_search_documents`、`memory_search_fts` | `memory_vectors`、`memory_vector_failures` | 索引服务；[记忆检索](memory.md) |
| 通知与诊断：已提交变化及执行记录 | `realtime_events`、`traces` | `trace_outbox`、`task_execution_events` | 事务事件与追踪服务；[实时通信](realtime-communication.md)、[可观察性](observability.md) |

例如，跟踪一次角色回复时，先从消息和输入批次确认收到的内容，再查看回应轮次、角色任务及结果。需要检查某条记忆的依据时，再查看对应的来源表。

多态原始来源按其正式类型及所属服务读取，外键绑定记录版本和事实支持版本。长期事实与认知的支持关系定义集中在[记忆设计](memory.md#5-长期事实和认知)。

### 1.1 游戏与局内决策

迁移 21 已建立 `game_games`、`game_seats`、`game_participations`、`game_opportunities`、`game_action_receipts`、`game_operation_receipts`、`game_events`、`game_event_audiences` 及宿主 `community_games` 表。游戏包保存有类型的完整记录，独立列保存正式查询与约束所需字段，由同一存储方法一起写入；所有修改使用调用者事务。

读取游戏及其回执、事件时，先用已保存的玩法与规则版本解析注册定义，再使用该定义 `GameModels` 中的具体模型恢复。局势、动作结果和终局结果保留所属类型，存储解析使用对应玩法的具体模型。

迁移 22 扩展会话类型为 `direct`、`group`、`game`，保留已有会话全部字段和引用，并建立 `game_session_operations`。宿主操作记录按创建请求或单局请求范围保存原命令、会话快照和变化的成员区间，游戏回执仍由游戏包维护。结算后结束活动只归档会话；未完成的活动结束时，同时取消对局并归档会话。

宿主测试数据维护按已选择社群读取对局关联，经游戏包 `GameCleanup` 统计和删除记录，同时删除所属的宿主操作记录、活动任务、结果和内心，范围外对局保留。真人参与协调、角色自动行动、局内会话、[活动输入与工作记忆](activity-context.md)、独立表达发布及[游戏经历消费者](activity-memory.md)均已接入；当前意图按对局生命周期清理。以下包含完整归属设计，实际字段见数据库参考。

迁移 31 新增活动任务与结果，重建 `thoughts` 以允许聊天结果或活动结果恰好一种来源，原聊天内心字段和内容保留。活动任务保存租约、原机会、固定请求编号及完整阶段产物；游戏、实际理解、意图、内心和结果使用同一短事务提交，失败时一起回滚。表达安排保存于结果，迁移 33 增加独立表达任务与恢复记录，正式消息通过会话服务提交。

迁移 32 增加 `activity_task_sources`，引用已有交流安排及其精确消息范围。任务区分行动与纯回应，纯回应没有机会编号和游戏动作回执；按游戏及参与编号限制一个有效任务。回应进度单独记录沉默与待表达，发布后才计算实际发言。原任务、回执、请求和内心完整保留，详见[局内协调](activity-coordination.md)。

迁移 23 扩展原 `realtime_events` 类型以保存 `game.changed` 引用和游戏来源，完整保留通知记录、自增序号与清理边界。通知与游戏及会话结果使用同一事务，重复引用在事务内合并，回滚不留下成功通知。通知的来源位置记录已提交棋局版本；正式游戏事件和实际受众仍由游戏包维护。HTTP 的列表与历史查询复用共同游标工具，读取范围和参与区间由宿主检查。

| 数据 | 权威维护者与用途 |
|---|---|
| 对局状态、创建者、席位占用、主体引用、参与区间、游戏状态、机会、随机结果、动作及生命周期回执、正式事件 | 独立 `echo_games` 包，通过游戏服务读写 |
| 对局所属社群、局内会话关联及宿主操作组合结果 | 社群侧参与服务，不重复保存主体与席位对应 |
| `game` 会话、固定成员、正式消息及 ActivityTask 来源关联 | 会话服务，保留实际受众和历史资格 |
| 局内决策任务、触发来源、抽样与执行方式、冻结输入、提议和结果引用 | Activity，通过既有执行设施调度 |
| 实际私人材料、游戏来源引用及精确处理覆盖 | 记忆服务，按角色资格和记忆模式处理 |

当前共享 SQLite。创建、加入、等待时离开和结束活动，通过游戏、会话及宿主关联服务在同一短事务保存，任一失败一同回滚；不设置待绑定状态。身份、历史区间和生命周期回执见[生命周期契约](../../../docs/gameplay/游戏与角色活动接口.md#3-对局生命周期与参与)。

角色动作、决策结果和表达恢复安排使用同一连接在动作事务内提交；正式消息在独立表达事务中保存，同时完成来源、social 发言额度和通知。模型调用在写事务外。动作事务失败时整体回滚；已提交动作不因后续发表失败而撤销，表达恢复也不会重复动作。具体规则见[局内表达](activity-expression.md)。

每次决策保存实际使用的紧凑游戏视图与原始来源，支持恢复当时输入；游戏保存完整历史，角色不维护第二份持续变化的棋盘。新增游戏事件来源需要一起实现读取资格、原始材料、精确覆盖与消费者。

游戏包维护自己的 SQL 资源，宿主继续使用唯一全局迁移入口。新增迁移、安装包资源与工作树数据库安排见[共同基础](../../../docs/gameplay/共同基础与文件结构.md)。

## 2. 模型调用与提交边界

运行先在短事务中冻结真实输入并建立任务，随后在事务外调用模型。返回结果经过节点与最终审核，在新的短事务中复核来源、观察资格、业务状态、记录版本和租约，再保存正式结果。

| 提交入口 | 同一事务保存 |
|---|---|
| 消息与回应 | 消息、受众、对应自身 Thought、回应结果、输入消费及后续安排 |
| 段反思 | 摘要、精确覆盖、合法状态与关系结果、段状态和运行结果 |
| 连续性压缩 | 新回顾、前驱绑定、覆盖、消费和运行结果 |
| 长期整理 | 事实或认知版本、逐项依据、事实支持映射、实际阶段覆盖、索引及运行结果 |
| 视图刷新 | 正文及引用、成功分支读取进度、变化消费和运行结果 |
| 测试数据清理 | 已检查范围内的正式记录、派生索引及通知边界 |

事实已完成而认知失败时，合法事实和事实阶段覆盖可以先提交；后续认知事务只完成剩余阶段。认知局部支持引用转换为实际事实版本后才保存。失败不能回滚此前成功事务，也不能提前消费尚未完成来源。

## 3. 约束、版本和重复

主键、唯一键、复合外键和 CHECK（数据库条件约束）保护身份、版本、归属与基本结构。原成员资格、消息受众、原始内容版本、参与者身份及业务更新资格由所属服务复核。模型只提出操作，不分配正式身份或写入权威表。

事实和认知分别保存稳定编号与版本，每个编号仅有一个当前版本。一次修订在同一事务保存新版本并结束旧版本；历史内容和引用仍保留。事实提取纠正与认知改变通过各自业务操作执行，不能用正文覆盖模拟版本更新。

客户端操作重复、执行尝试重复、阶段提交重复、来源消费重复各有实际身份。重试复用已保存结果和覆盖，不能增加第二份关系影响或重复事实依据。较旧版本的候选不能覆盖后来保存的认识。

合法业务拒绝保留明确决定，候选不写入业务表。实际数据库错误回滚当前事务中的记录、来源、消费和运行结果。StorageError（存储错误）保留实际原因，HTTP 与任务入口分别转换。

## 4. 结构升级与数据重建

已投入使用的结构通过新增迁移变更，不修改历史迁移。每份脚本全部完成、检查完整性后才登记 schema_migrations；失败不保留半份结构或成功版本。普通连接启用外键，初始化启用 WAL（预写日志）及实际等待策略。

迁移需要重建被引用表时，在专用连接事务外暂停外键检查，提交前执行全库 foreign_key_check（外键检查），任何错误均回滚。迁移不是模型调用入口。

长期重建先备份并导出旧记录及来源，检查实际原文是否可读，再通过正式反思流程形成新记录。旧混合正文不能凭标签、关键词或模型自报置信度直接转换。原文、状态历史、关系数值和密钥保留；实际处理规则见 [数据重建](memory.md#9-数据重建与模块职责)。

正式存储不进行旧格式双写或运行时转换。原始历史审计保留独立读取；已取消旧协议任务不能恢复执行。只读检查和导出使用实际只读连接，数据库不存在时明确失败；备份拒绝覆盖已有目标。

## 5. 投影、通知和诊断

全文与可选向量索引从正式记录建立，保存源类型、身份和版本。索引不能扩大读取权限；版本变化后旧投影不参与查询，后台计算期间不占用写事务。

SSE（服务器推送）事件和诊断元数据随所属提交事务登记，提交后再通知连接。完整模型捕获独立保存，不能作为发生事实或恢复权威状态的唯一依据。规则见 [实时通信](realtime-communication.md) 与 [可观察性](observability.md)。
