# 任务 1：有效行为与删除清单确认

确认日期：2026-10-01  
状态：已完成代码与设计核对；后端实施从任务 2 开始  
依据：[实施计划第 3 节](03-backend-implementation-plan.md#3-任务-1确认有效行为和删除清单)、[目标结构](02-backend-file-structure.md)、[数据库设计](05-database-design.md)、[验收要求](04-backend-baseline-and-acceptance.md)

## 1. 确认结果

任务 1 已完成。现有代码中可以保留的算法、需要替换的运行边界、旧文件的调用方、测试验证目标和数据库消费者均已确认。按既定方案继续任务 2，无需增加旧接口兼容路径。

本次只新增确认记录并更新方案索引。源码、配置、人物资源、旧迁移和用户数据保持原样。没有启动服务、调用模型或执行旧测试，也没有创建新业务数据库。

### 1.1 核对范围与实际证据

| 项目 | 实际结果 |
|---|---|
| 开始时工作区 | `git status --short` 无输出，工作区干净 |
| Python 源码 | 使用标准库 `ast` 解析全部 143 个文件，核对定义、导入与调用入口 |
| 测试 | 43 个 `test_*.py`、3 个辅助文件；共有 288 个顶层测试函数定义，参数化运行数量另计 |
| 旧包导入 | 源码与测试合计 170 个文件仍导入 `echo_server` |
| 历史迁移 | 在独立的内存 SQLite 3.45.3 中顺序执行全部 16 份 SQL，读取最终表、字段和外键；`PRAGMA foreign_key_check` 返回空列表 |
| 旧结构规模 | 36 个显式表对象，包含 FTS5 全文表和迁移表；SQLite 自动维护的全文内部表和序号表不计入 |
| 新结构规模 | 05 定义 43 个显式表对象，包含 FTS5 全文表和迁移表；逐表核对见第 6 节 |
| 仓库外工具 | `tools/dev/echo_runtime_data.py` 和 `contracts/openapi/echo-agent-service.json` 在当前仓库均不存在 |
| 数据文件 | 当前 `server/data/` 存在旧实验 SQLite 及附属文件；未读取或改动它们 |
| 新数据库 | `server/data/echo-commons.sqlite3` 尚不存在；确认后续程序只使用此新路径 |

内存 SQL 检查证明历史脚本能够在空库产生所列结构。它没有执行正式异步迁移器，也没有验证已有用户数据的升级；这些工作不属于本次确认。新 SQL 尚未生成，其约束和事务将按任务 3 实测。

### 1.2 实施时必须处理的具体问题

| 当前事实 | 必须采用的处理 |
|---|---|
| 包目录已改名，内部导入、打包目录和 README 命令仍指向 `echo_server` | 任务 2 同时更新发行名称、内部导入、资源路径与实际入口；不创建别名包 |
| 对话准备与提交限定 DIRECT 会话、恰好一个角色，任务唯一性也按会话限制 | 任务 5、7 替换为一个执行中 SocialTurn、多份角色任务；单角色数量检查删除 |
| 对话快照在执行前重新组装；反思恢复通过重建材料并比较版本取回快照 | 任务快照与图快照保存完整输入；恢复读取原快照，不重新选择当前材料 |
| 反思来源按整个会话序号区间取消息，检索索引按会话角色列表分发消息 | 任务 4、8 使用实际消息受众及精确来源；序号上下限只用于排序和观察边界 |
| 关系事实提交把目标固定为账号；反思消息材料缺少明确发送主体 | 关系候选携带玩家或角色目标，材料携带 ActorRef；按目标和维度分别审核与去重 |
| 一次输出可以投影为多条数据库气泡，归段需要防止气泡被截断 | 一次发言保存一条完整消息；删除气泡分割、编号、完整气泡前缀算法 |
| 缺少凭据时 `auto` 可以选择 Stub；Agent 属性与模型路由存在动态猜测 | 只登记真实后端；缺少必要配置明确报错；能力、版本与路由通过显式契约提供 |
| `thought_provenance` 由触发器同步，当前 Python 代码没有直接查询消费者 | 合并到 `thoughts`，清除文本时保留身份和来源；删除双份同步触发器 |
| wheel 打包枚举人物资源时遗漏 `voice.md`，SQL 也未见明确的随包包含规则 | 任务 2、9 打包完整资源与 SQL，并在源码目录外验证安装包 |
| `numpy`、`onnxruntime`、`sqlite-vec`、`tokenizers` 已声明，但全部源码未发现对应运行调用 | 任务 10 删除没有正式消费者的这些直接依赖并更新锁文件；保留实际分词与 FTS5 检索，不增加嵌入模型实现 |

## 2. 保留能力、状态归属和验证目标

下列包内路径以 `server/src/echo_commons/` 为起点。保留表示复用实际规则或算法，现有类签名与文件布局按 02 替换。

### 2.1 正式模型适配

实际入口为 `services/model_gateway/openai_compatible.py:OpenAICompatibleGateway.generate`，由 `registry.py` 读取逻辑模型、供应商设置与凭据，再使用 `AsyncOpenAI` 发出请求。

保留供应商响应标准化、工具调用解析、流式结果处理、期限限制、可重试错误分类、供应商重试次数及用量记录。`routing.py:TaskRouting.route_for` 的显式任务路由保留；已有 strong/light 配置选择可以继续决定真实模型，不保留缺少 Agent 属性时的猜测路由。供应商协议中的 `tool_choice="auto"` 是正常工具选择参数，与删除的后端自动选择 Stub 无关。

模型客户端与用量记录归 `infrastructure/models/`，不保存业务状态。供应商级重试、Harness 格式修正、持久任务重试分别计数。模型网络请求不持有 SQLite 写事务。

验证：配置解析使用真实 TOML；响应标准化使用正式类型；供应商异常分类使用真实 SDK 异常对象；模型行为由真实供应商调用验证。删除脚本化 FakeClient、FakeCompletions 和 FakeModelGateway。

### 2.2 Harness 与角色 Agent

实际入口为 `agents/character/agent.py:CharacterAgent.run` → `agents/harness/runner.py:EchoNativeBackend.run` → `loop.py:AgentLoop.run`。

保留不可变调用身份、调用目的、允许工具、输出契约、模型步骤和请求预算、工具预算、期限、有限格式修正，以及 `progress.py:ToolProgressState.observe` 的真实材料进展判断。相同工具结果没有新增材料时，连续无进展次数增加；取得新材料时清零。这会改变后续执行，因此有保留价值。

调用期间状态归单次 Harness 执行；角色长期状态归 characters，记忆归 memory。Agent 不直接访问数据库。工具由正式只读服务提供，调用主体来自 Runtime 创建的 scope（调用范围）。

验证：纯预算、进展和输出解析规则直接调用正式对象；完整模型工具循环使用真实模型与真实记忆查询。删除只返回预设回复的 Agent 和工具替身。反思专用输出契约移入 reflection，由 app 注册给通用 Harness。

### 2.3 玩家输入与安静窗口

实际入口为 `runtime/conversation/intake.py:ConversationIntakeService.submit_message` 和 `seal_due_input_batches`，规则在 `domain/input_batch.py`，数据库写入在 `store/runtime_repositories.py`。

保留同一请求重复提交返回原消息、内容冲突明确报告、重复请求不延长窗口、窗口从最后一条新消息开始计算、窗口到期后新消息先结束旧批次的规则。当前按账号和会话收集的范围替换为会话、ActorRef 和实际受众。原请求载荷哈希删除，正式消息字段足以比较请求内容。

权威消息、批次和精确关联归 conversations；玩家发送事务同时处理身份、序号、受众、幂等、批次和追踪待投递记录。角色使用同类批次，窗口为 0，在输出提交事务直接结束收集。

验证：真实 SQLite、正式消息服务、明确时间参数；覆盖玩家交错发送、不同受众、到期边界、重复请求和角色单次输出。

### 2.4 租约、恢复与任务分发

实际入口为 `runtime/dispatcher/dispatcher.py:TaskDispatcher`、`lease.py:LeaseHeartbeat`、`domain/task.py:ConversationTask.has_valid_lease`，任务领取、续期与恢复由 `ConversationTaskRepository` 完成。反思节点有对应 `ReflectionGraphTaskStore`。

保留任务领取的短事务、执行者身份、有效期限、尝试次数及 lease_generation（领取代次）检查。同一个执行者重新领取任务后，旧代次结果仍必须失效。保留到期任务恢复、有限重试、永久失败、取消、关闭停止领取与在途任务处理。

业务任务状态保存在各模块队列表中；通用分发、心跳和并发管理归 execution，不再从全局默认账号取得范围。对话与反思使用独立队列适配；以后 ActivityTask 拥有自己的队列和提交入口。

验证：真实 SQLite 上领取、续期、推进到期时间、重新领取并提交旧代次结果；正式生命周期关闭并重新启动。数据库事务回滚通过真实约束冲突触发，删除注入异常的数据库子类与函数替换。

### 2.5 对话审核与原子提交

实际入口为 `runtime/conversation/commit.py:ConversationCommitService.commit_task_result`、`runtime/proposals/reviewer.py:ProposalReviewer.review`、`handlers/character_message.py:CharacterMessageHandler.review`。

保留执行身份一致、提案调用来源一致、重复结果判定、单任务唯一批准结果、非空发言与长度校验、私有 Thought 与公开审计载荷分离。模型主动沉默属于成功结束，不能生成空消息。

权威写入归 conversations/tasks/commit。一个事务保存结果、完整发言、实际受众、角色零窗口批次、私有 Thought、任务与参与状态，再更新 SocialTurn 完成状态。受众沿用来源轮次仍有效的原成员区间；成员重新加入不能接收原区间的迟到结果。

现有 `conversation.context_version == task.context_version` 整体比较不能原样保留：同轮次第一位角色提交消息后，第二位角色仍需使用原快照正常提交。新提交检查围绕任务身份、租约、原成员区间、归档和暂停规则执行。

验证：真实服务与 SQLite，覆盖双角色分别提交、沉默、重复、迟到、退出后重新加入、私有 Thought 隔离，以及提交中真实约束失败时全部回滚。

### 2.6 角色状态与关系规则

实际规则入口为 `domain/character_state_entry.py:replace_character_state_entry` 和 `domain/relationship.py:apply_relationship_evidence`。存储由 `store/state_repositories.py` 负责，反思写入由 `runtime/reflection/facts.py` 调用。

保留按状态类别递增的历史记录、有效时间、期望版本检查，以及有向关系和真实证据来源。关系变化使用离散等级 0—3，按既有步长、关系类型系数和距 0/100 边界的比例更新；数值保持 0—100。初始化、成为朋友的资格证据、依恋资格、同一证据同维度唯一性继续有效。

关系状态归观察角色，不自动反向复制。原 account 目标替换为明确的 player 或 character。同社群中的两个同模板实例没有共享状态。原剧情缺席与技术错误角色状态删除；技术错误归任务与诊断。

验证：正式领域对象计算边界、初始化和版本冲突；真实 SQLite 保存证据与关系，验证实例和目标隔离。反思审核后的证据、状态和图级结果在同一提交事务内保存。

### 2.7 记忆来源、归段和检索

实际入口为 `services/memory/bootstrap.py:MemoryInitializationService`、`sealing.py:MemorySegmentSealingService.seal_unsegmented_messages`、`retrieval.py:MemorySearchService`、`runtime/memory/search_tool.py:MemorySearchTool.invoke` 和 `store/memory_provenance.py:MemoryProvenanceRepository`。

保留正式预置记忆、角色独立经历、摘要消费记录、连续性摘要链、长期记忆整理消费、来源版本失效、私有内容限制，以及 jieba 分词与 SQLite FTS5 检索。已有来源版本计算只在决定重用、审核或消费时继续使用。

替换会话区间全量取消息、按全体角色建立索引、全局账号绑定工具和模板 ID 作为实例 ID 的用法。角色可见的完整消息及其自身 Thought 进入精确来源关联；来源上下限不能代替消息列表。Thought 原文清除后保留同一记录的来源身份。

状态归 memory，客观可见性由 perspective 与 conversations 的共同规则提供。归段、摘要提交、整理消费和全文映射更新各自使用明确事务；同一次事实提交调用跨模块存储时共用连接。

验证：真实实例初始化、真实消息与 FTS5 查询；覆盖不同成员历史、私聊不可检索、离开后保留过去经历、重复处理、失效来源和清除后的来源身份。检索索引可以按合法来源重建，未完成的向量检索不进入本次实现。

### 2.8 追踪、日志与诊断

实际入口为 `store/trace_repository.py:TraceRepository`、`runtime/trace/delivery.py:TraceDeliveryService`、`observability/trace.py`、`reflection_run_view.py` 与 `debug_capture.py`。

保留业务事务只写 trace_outbox、独立投递、投递去重与恢复、有限重试、私有原文过滤和明确启用的本地模型捕获。日志、追踪与诊断不会成为业务事实来源。

诊断归 infrastructure/observability，路由组合归 app；删除面向旧工作台的 URL 和响应命名。关闭供应商连接、数据库与 Worker 的责任由 app/lifecycle 明确承担。

验证：真实 SQLite 待投递记录领取与投递、真实文件日志和捕获、正式健康端点；不修改 Worker 方法制造失败。

## 3. 三种已实现反思图

### 3.1 入口与事实提交

| 图 | 实际调度入口 | 已存在的节点与处理 | 权威提交 |
|---|---|---|---|
| `segment_reflect` | `runtime/reflection/workflow.py:ReflectionGraphScheduler.schedule_segment_reflection` → `coordinator.py:start_segment` | 段摘要计划 → 按条件执行关系/状态反思 → 段聚合 | `executor.py:_finish_if_ready` 审核后调用 `facts.py:ReflectionGraphCommitService.commit`；写段摘要、覆盖来源、关系证据和实例状态，段进入已处理状态 |
| `continuity_compress` | `schedule_continuity_compression` → `start_continuity_compression` | 连续性压缩 → 聚合 | `review.py:review_continuity_compression` 后调用 `commit_continuity_compression`；写新摘要、前一摘要关联和精确消费来源 |
| `memory_organize` | `schedule_memory_organization` → `start_memory_organization` | 记忆页生成与实体图提取 → 聚合 | `review.py:review_memory_organization` 后调用 `MemoryOrganizationCommitService.commit`；写记忆页、实体、别名、关联和边，再保存消费结果 |

图定义在 `domain/reflection_graph.py:reflection_graph_definition`，节点输入在 `runtime/reflection/node_input.py:NodeInputProjector.project`，模型执行在 `executor.py:ReflectionGraphExecutor.execute`，持久对象在 `store/reflection_graph_repositories.py`。

这些入口存在于源码。现有反思运行测试使用 Stub 与预设产物，本次没有把其通过情况当作真实模型完成证据。

### 3.2 必须保持的规则

1. 图拥有确定的角色、版本、快照与来源范围；节点只使用已声明字段和真实前置产物。
2. 同图同节点只有一份任务；满足依赖并被激活后才能领取。
3. 成功产物不可变；提交验证节点租约、尝试次数、输入和契约。
4. 关系和状态节点可以不激活；合法 no_op（无需修改）必须保存原因，已处理来源仍标记消费。
5. 必需节点失败导致图失败；可选节点失败允许保留有效产物并形成 partial（部分结果）。
6. 聚合、审核结果、业务事实和消费记录共同提交；重试不能再次增加关系数值或生成重复记忆。
7. 连续性压缩和长期记忆整理有独立消费依据，一方处理后不能使另一方漏掉材料。
8. 保留会改变重用、审核与消费结果的现有输入和产物指纹；不新增无消费者的指纹。
9. 图恢复改为读取持久化完整快照，后续新消息、角色状态更新不会替换原始输入。

验证方法：纯图定义、输入投影、标准化和审核使用正式对象；图队列与消费使用真实 SQLite；三种图的模型执行与正式事实写入使用真实材料、真实 Agent 和真实模型。

### 3.3 保持未实现的能力

`diary_compose` 与 `view_refresh` 有图定义、输出契约及部分存储，正式 scheduler 只提供上述三种入口，executor 的图级提交也只接受上述三种图。保留现有类型和存储，继续明确标记正式调度与事实写入未实现。

自动往事识别、角色连续主动聊天、模型参与意愿、人物生成、生活日程和 Activity 保持 03 第 13 节的范围。本次没有活动目录、活动表、ActivityTask 队列或小游戏代码。

## 4. 公开端口与依赖归属

此处确认端口职责，实际文件名以 02 为准，字段和数据库结构以 05 为准。

| 模块 | 公开读取能力 | 公开写入能力与事务发起者 | 依赖 |
|---|---|---|---|
| communities | 玩家身份、社群成员、社群时间与暂停 | 玩家/社群登记、社群成员登记、暂停恢复；应用服务发起事务 | 自身存储与 shared 引用 |
| characters | 模板、实例、能力、当前自身状态、有向关系 | 创建实例、变更可用状态、追加审核状态与关系证据；创建服务或反思提交发起事务 | communities 身份读取、memory 预置写入端口、自身存储 |
| conversations | 会话、成员区间、按读取主体过滤的消息、任务和结果 | 会话/成员操作、玩家发送、任务领取与发言提交；所属服务发起事务 | communities、characters、perspective、memory 的明确端口，AgentRegistry |
| social | 来源轮次、候选决定、轮次完成情况 | 规划来源、记录参与、更新完成；规划或结果提交事务 | 会话来源与任务创建端口、社群状态、角色可用状态 |
| perspective | 指定角色在指定范围内的可见事实与有效来源版本 | 无事实写入 | 各业务只读契约；不依赖任务执行器 |
| memory | 私有记忆、摘要、精确来源、合法检索 | 预置、归段、摘要/记忆写入、覆盖与消费、索引更新 | 实例身份、会话可见来源、自身存储 |
| reflection | 已有图、节点、产物、来源与诊断 | 调度三种图、领取节点、审核及事实提交 | perspective、characters、memory、AgentRegistry、execution 契约 |
| execution | Worker 状态与模型额度 | 分发已注册处理器、租约心跳、资源领取释放 | 任务队列契约和处理器契约；不直接决定聊天或玩法规则 |
| infrastructure | 数据库连接、真实模型、诊断记录 | 基础连接和追踪投递 | 不拥有默认角色、账号或剧情 |
| app | 向 HTTP、CLI 提供已组装服务 | 加载配置、组装对象、生命周期 | 注入具体实现；不复制领域规则 |

跨模块依赖通过明确读写端口连接。组装器注入实现，不让 characters 与 memory 等模块互相导入具体服务造成循环。事务由发起者持有；被调用的 Repository 使用传入连接，不能在内部再开启一项业务事务。

## 5. 文件、旧调用方与删除顺序

### 5.1 按现有文件确认处理位置

以下覆盖当前源码目录。`__init__.py` 跟随实际包组织更新，删除兼容导出与重复转发；不会因保留算法而保留旧导入路径。

| 现有文件或目录 | 已确认调用方 | 处理及目标 |
|---|---|---|
| `main.py`、`config.py` | HTTP 应用、factory、生命周期、几乎全部运行服务 | 入口、配置和资源相对路径重写为 `app/`；当前源码没有独立 `cli.py`，新 CLI 按正式需求创建 |
| `runtime/application_runtime.py`、`runtime/modules.py` | API dependencies、对话/反思/记忆/追踪服务与测试 | 删除聚合转发、模块基类、RuntimeControls；依赖组装归 app/composition，业务入口归各模块，后台控制归 execution |
| `runtime/lifecycle.py` | ApplicationRuntime 与 HTTP lifespan | 保留初始化、到期恢复与关闭职责；删除默认会话、全模板账号记忆和 meta 启动写入；归 app/lifecycle |
| `runtime/common.py` | intake、preparation、commit、sync、worker、ApplicationRuntime | 游标归 conversations/query；时钟归 execution；请求直接字段比较归发送服务；删除哈希和转发 |
| `runtime/input_preparation.py`、`runtime/eligibility.py` | ApplicationRuntime、准备与提交 | 删除 Offline 包装和旧剧情规则；实际批次、参与、实例可用判断归 conversations/social/characters |
| `runtime/conversation/intake.py` | message 路由与 Worker | 按 ActorRef/受众改写为 conversations 发送与输入服务 |
| `runtime/conversation/preparation.py` | ConversationWorker、ApplicationRuntime | 替换为 social/planner 和 conversations/tasks/context，删除群聊拒绝及唯一角色假设 |
| `runtime/conversation/execution.py`、`handler.py`、`commit.py` | dispatcher、ConversationWorker | 保留执行、审核和原子提交算法，归 conversations/tasks；使用实例注册表和保存的快照 |
| `runtime/conversation/sync.py` | 旧同步路由与 ApplicationRuntime | 删除账号整体同步，按玩家/会话范围读取，归 conversations/services/query |
| `runtime/conversation_worker.py` | HTTP lifespan、health | 拆分社交规划、任务执行和追踪循环，归 execution/workers 与 supervisor |
| `runtime/dispatcher/`、`runtime/recovery.py`、`runtime/errors.py` | 对话和反思 Worker、执行器 | 通用分发/租约/恢复归 execution；具体对话队列与恢复决定归 conversations/tasks，业务错误归所属模块 |
| `runtime/proposals/` | 对话 commit 与 executor | 发言审核归 conversations/tasks/review；具体反思审核留 reflection；删除对所有用途限定单一种提案的通用包装 |
| `runtime/memory/search_tool.py` | Agent factory 与 Harness 注册 | 移入 memory/tools/search，取消构造时绑定账号；执行主体由 ToolContext 的明确范围提供 |
| `runtime/reflection/` | ReflectionWorker、scheduler、dispatcher、诊断 | 保留三图真实算法，分入 reflection 的上下文、任务、审核和事实提交；删除全局 Runtime 依赖与动态来源探测 |
| `runtime/trace/` | 对话与反思 Worker、ApplicationRuntime | 追踪投递独立化，移入 infrastructure/observability/delivery |
| `domain/conversation.py`、`messages.py`、`input_batch.py`、`task.py`、`result.py`、`proposals.py` | 对话服务、Repository、API 与 Agent 契约转换 | 规则归 conversations/domain，替换账号主体与批次状态；删除 project_bubbles 和旧别名 |
| `domain/state.py`、`character_state_entry.py`、`relationship.py` | eligibility、准备/提交、反思 facts、状态 Repository | 社群时间暂停归 communities；实例可用状态与内部状态/关系归 characters；删除 WorldState 单例及旧状态 |
| `domain/memory.py`、`memory_sources.py` | 记忆服务、反思上下文和事实提交、存储 | 移入 memory/domain，新增实例范围与精确来源；保持既有记忆与摘要算法 |
| `domain/reflection*.py` | 图调度、节点执行、normalizer、review、存储 | 移入 reflection/domain；保留未完成图的有效定义，更新版本 |
| `domain/errors.py` | 全部领域规则 | 共用基础错误归 shared/errors；领域校验辅助随实际使用归属，不建立杂项工具层 |
| `store/runtime_repositories.py` | 全部对话服务及上下文读取 | 拆入 communities、characters、conversations、social；旧接口与单会话任务唯一查询删除 |
| `store/state_repositories.py` | 状态读取、关系读取、反思 facts | 拆入 characters/repositories；关系目标和实例范围更新 |
| `store/memory_repositories.py`、`memory_provenance.py`、`memory_search_repositories.py`、`memory_view_sources.py` | 记忆服务、上下文、反思 facts 与诊断 | 拆入 memory/repositories/services；删除按区间推定来源与完整气泡前缀逻辑；保留有效派生视图失效判断 |
| `store/reflection_graph_repositories.py` | coordinator、executor、graph_queue、diagnostics | 拆为 reflection 四种对象的 Repository；图保存完整快照 |
| `store/database.py`、`migrations.py`、`repository_support.py` | 所有 Repository、lifecycle | 基础连接、事务、SQL 加载与记录映射归 infrastructure/database；保留标准 SQLite 完整语句解析 |
| `store/meta_repository.py` | lifecycle 与 ApplicationRuntime | 删除；结构版本归 schema_migrations，进程启动状态归 app 诊断 |
| `store/trace_repository.py` | 追踪投递、任务/图提交 | 移入 infrastructure/observability/repository；保留正式队列与投递事务 |
| `store/sql/0001—0016` | migrate、旧升级测试 | 任务 3 新空库结构验证后全部删除；新 SQL 按 05 创建有效结构 |
| `services/context/` | 对话 snapshot_builder、反思 assembler、ApplicationRuntime | 删除该通用混合模块；客观读取归 perspective，任务组装归 conversations/reflection，内部信息与记忆由所属模块提供 |
| `services/identity/` | context、factory、bootstrap、Agent 测试 | 移入 characters/templates；删除 schema 双格式、from_legacy、单文件角色和旧资源类型兼容 |
| `services/memory/` | 启动、归段、反思及搜索工具 | 移入 memory/services；tokenization 保留真实 jieba 与 FTS 查询职责 |
| `services/model_gateway/` | factory、Harness、Agent、节点 executor | 正式实现移入 infrastructure/models；删除 fake.py、重复 output_schema 字段、legacy 输出解析与动态 Agent 路由 |
| `agents/factory.py` | main 与模型烟雾测试 | 删除默认角色构造，替换为 characters/services/registry 与 app 组装 |
| `agents/stubs/` | factory、各类旧测试 | 删除实现、导出、模型配置分支及全部替身调用方 |
| `agents/character/`、`agents/harness/` | 对话和反思执行 | 保留正式执行算法，更新身份/快照/输出注册；删除属性动态猜测与旧快照别名 |
| `agents/contracts/reflection.py`、`reflection_context.py`、`reflection_graph.py` | 反思 domain/runtime、Harness output 与 prompt | 业务专有类型归 reflection/contracts；通用调用及输出注册留 agents/contracts，app 注入实际解析器 |
| 其余 `agents/contracts/` | Agent、Harness、任务执行、网关 | 保留实际通用定义，移除账号、旧快照与硬编码旧版本，按初始契约重写 |
| `api/` | main、旧客户端和 tests | 路由归各模块；聚合和诊断归 app；删除旧 message/send、message/sync、聚合 health、camelCase 别名及未实现图片等字段 |
| `observability/` | 模型、Harness、任务、Worker、诊断 | 移入 infrastructure/observability；保留有效输出过滤和捕获，更新身份与来源 |
| `config/identity/` | loader、Prompt、预置初始化、打包与测试 | 人物正文保留为模板资源，完整移入 resources/identity；重置有效元数据版本，实例信息不放入模板 |
| `config/settings.toml`、`model-registry.toml` | Settings、gateway、factory | 删除默认业务身份与剧情、Stub 和自动替身模式；保留真实模型设置与有消费者的运行预算 |
| `config/model-secrets.toml` | 正式凭据加载 | 保留用户文件与忽略规则；不读取密钥内容、不写入文档、不加入 Git |
| `pyproject.toml`、`uv.lock` | 安装、打包、工具运行 | 更新发行名称、资源/SQL 包含、命令和正式测试标记；按实际消费者更新依赖及锁文件 |
| `server/README.md`、`server/docs/`、旧 ADR | 当前开发说明 | 在对应实施后修订实际行为；任务 10 整理工程文档，删除旧阶段与客户端约定，保留仍有效的决策理由 |

### 5.2 仓库外引用与旧产品验证

| 引用位置 | 当前依赖 | 替换 |
|---|---|---|
| `server/README.md`、`test_runtime_data_tool.py`、`test_state_scenarios.py`、旧 SQL 注释 | 缺失的 `tools/dev/echo_runtime_data.py` | 包内 `app/cli.py` 的 init、inspect、export，真实示例使用正式服务；旧工具场景测试删除 |
| `test_conversation_runtime.py:test_openapi_contract_is_current` | 缺失的仓库级 OpenAPI JSON | 从新应用生成正式 OpenAPI，验证新公开接口；删除旧合同文件依赖 |
| 小槿 golden.yaml 与回归测试 | 固定旧场景、旧版本及固定输出文本约束 | 删除旧版本/剧情断言；模板内容加载、完整资源、角色身份与真实输出契约验证重新组织 |
| 旧工作台与 Unity 说明 | 原产品路径和专属交互约定 | 新接口、内部诊断与新 CLI 的实际说明 |

人物资源中小槿的真实人格、语气与预置记忆仍是有效模板内容。删除旧产品测试不会把真实人物模板删除。`docs/temp_doc/` 继续作为原始参考材料保留。

### 5.3 删除时机

任务 2 删除旧包接口、Stub/Fake、旧人物格式与重复模型契约；任务 3 新结构验证后删除旧 SQL；任务 4—8 在所属新路径建立后删除旧来源读取、气泡、全局身份与混合 Runtime；任务 9 替换旧 HTTP 和外部工具；任务 10 清理遗留导出、旧测试、无消费者依赖与工程文档。

每项删除同时更新表中调用方。实施只维护当前设计，不要求中间步骤能启动旧系统。任务 1 的确认阶段没有执行上述删除。

## 6. 数据库逐表确认

字段、允许值、外键和索引仍以 [05](05-database-design.md) 为唯一设计定义。下表确认每个对象的实际用途、现有依据和必须处理的结构差异；不再复制一份字段字典。

“新增”表示新平台需求；“保留重建”表示现有有效数据行为需要适配实例和社群；“合并”表示删除重复结构。

| 新表 | 现有依据或新消费者 | 关键约束、查询或差异 | 确认 |
|---|---|---|---|
| `communities` | 社群登记/状态读取；旧 world_state 的时间与暂停 | 社群范围和状态版本；删除全局单例与 phase | 新增并合并 |
| `players` | 玩家登记及消息身份解析 | 玩家 ID 稳定，姓名不当身份 | 新增 |
| `community_members` | 社群登记、创建实例和会话身份校验 | 社群与 ActorRef 唯一；多态真实存在性由同一事务校验 | 新增 |
| `character_instances` | 模板绑定、AgentRegistry；旧 character_states | 实例所属社群、模板版本、可用状态版本；两个实例独立 | 新增并合并 |
| `character_state_entries` | StateEntryRepository、context 与反思 StateFactHandler | 同实例同种类版本唯一，读取各类最新状态，保存历史 | 保留重建 |
| `relation_evidence` | RelationshipEvidenceRepository、RelationshipFactHandler | 观察者/目标范围和真实来源；明确 player/character 目标 | 保留重建 |
| `relationship_state` | RelationshipStateRepository、上下文关系读取 | 有向关系主键、数值/初始化检查和期望版本 | 保留重建 |
| `conversations` | 会话服务、RuntimeConversationRepository | 社群归属、归档、成员版本、按会话分配序号 | 保留重建 |
| `conversation_memberships` | 旧 ConversationParticipantRepository、所有可见消息读取 | 独立成员区间、当前资格唯一、序号边界；重新加入创建新区间 | 替换旧成员表 |
| `messages` | 发送、读取、审核提交、索引与归段 | 一次发言一行；结果唯一；玩家幂等字段合并；回复同会话 | 保留重建 |
| `message_mentions` | 新消息提及和参与选择 | 同消息主体唯一，发送事务校验实际主体 | 新增 |
| `message_recipients` | perspective、玩家增量、检索及归段 | 公开/私有均记录实际成员区间；不向新加入者扩展旧受众 | 新增 |
| `input_batches` | intake、到期收集与 social/planner | collecting/sealed；同主体同受众唯一收集中批次；删除 task_id 与执行状态 | 保留重建 |
| `input_batch_messages` | 发送事务与来源读取 | 每条消息只属于一个批次；精确列表替代交错序号区间 | 新增 |
| `social_turns` | social/planner、完成计算、轮次状态 API | 每会话唯一执行中轮次；同受众来源与观察边界 | 新增 |
| `social_turn_batches` | 规划消费与恢复 | 一个批次只被自动轮次消费一次；角色批次保留因果来源 | 新增 |
| `participation_decisions` | 确定性选择、结果提交与完成查询 | 每轮次每角色唯一；任务反向查询，删除重复 task_id | 新增 |
| `conversation_tasks` | TaskRepository、队列、执行与提交 | 轮次/角色唯一、完整快照合并、原成员区间、租约与代次 | 保留重建 |
| `conversation_results` | 旧 AgentResultRepository、正式发言提交 | 任务/尝试唯一、唯一批准结果；明确只属于对话 | 重命名重建 |
| `memory_segments` | sealing、SegmentRepository 与段反思 | 实例可见经历、来源版本和状态；序号范围不代表完整来源 | 保留重建 |
| `memory_segment_sources` | 归段、反思材料与覆盖校验 | 精确消息/自身 Thought 来源与顺序，同实例来源资格 | 新增 |
| `memory_entries` | preload、MemoryEntryRepository、整理事实与查询 | 实例/记忆 ID 可供复合引用，有效期限、私有资格与来源 | 保留重建 |
| `thoughts` | 对话提交、段材料、来源清除 | 结果和实例同范围；文本可清除；来源元数据同一行保留 | 保留并合并 |
| `memory_source_coverage` | MemoryProvenanceRepository 的 record_coverage 与清除资格 | 来源/版本精确覆盖，重复内容一致；跨角色范围明确 | 保留重建 |
| `memory_summary_batches` | freeze_batch/get_batch、压缩与整理 scheduler | 冻结来源版本及前一摘要，恢复原批次；消费者独立 | 保留重建 |
| `memory_summary_batch_items` | 批次验证与来源遍历 | 批次内段唯一，保存准确摘要版本 | 保留重建 |
| `conversation_digests` | latest_digest、上下文连续性及 commit_digest | 批次唯一；前一摘要从批次取得，删除重复链接 | 保留重建 |
| `memory_organization_consumption` | commit_organization 与待整理查询 | 段/摘要版本唯一；合法 no_op 也消费 | 保留重建 |
| `diary_entries` | DiaryEntryRepository、既有覆盖类型 | 实例/日期唯一；保留存储，正式生成流程未实现 | 保留重建 |
| `memory_views` | MemoryViewRepository、view_source_version、上下文 | 实例/视图种类唯一，来源失效检查；正式刷新流程未实现 | 保留重建 |
| `memory_entities` | MemoryOrganizationCommitService 与 MemoryGraphRepository | 角色私有索引实体，同实例引用；不会变成世界事实 | 保留重建 |
| `memory_entity_aliases` | 实体按名称解析 | 规范名称的有效部分唯一性，同角色实体外键 | 保留重建 |
| `memory_entry_entities` | 记忆页/实体关联写入及查询 | 记忆和实体均使用同角色复合外键 | 保留重建 |
| `memory_edges` | 图提取提交、MemoryGraphRepository | 同实例端点和来源；无来源边使用部分唯一解决 NULL 去重 | 保留重建 |
| `memory_search_documents` | MemorySearchRepository、来源版本过滤及重建 | 实例/来源唯一、可见来源映射，不读取他人私聊 | 保留重建 |
| `memory_search_fts` | 实际 jieba/FTS5 查询 | rowid 对应文档映射，同事务更新；可重建的查询投影 | 保留重建 |
| `reflection_graph_runs` | GraphRunRepository、coordinator 与恢复 | 角色/图/版本/快照来源唯一；保存完整快照和 partial | 保留重建 |
| `reflection_node_tasks` | NodeTaskRepository、graph_queue 与依赖调度 | 图/节点唯一、激活与依赖、租约代次；删除反向 artifact_id | 保留重建 |
| `reflection_artifacts` | ArtifactRepository、normalizer 与图聚合 | 节点/尝试唯一、同图复合外键、不可变输入与契约 | 保留重建 |
| `reflection_graph_results` | GraphReviewRepository、图级审核提交 | 同图唯一结果，决定字段与终态一致 | 保留重建 |
| `trace_outbox` | TraceRepository、独立投递 Worker | 待投递身份唯一、有限重试和完整 processing 租约 | 保留重建 |
| `traces` | 投递历史与内部来源链查询 | trace_id 去重；投递插入与 outbox 删除同事务 | 保留重建 |
| `schema_migrations` | 正式迁移器 | 唯一结构版本，初始版本 1；删除 meta 的同义版本 | 保留重建 |

### 6.1 删除的旧数据库结构

| 旧结构 | 实际消费者与处理 |
|---|---|
| `world_state` | context/eligibility/准备/提交读取；时间暂停改读 communities，剧情字段删除 |
| `character_states` | 角色可用性读取；合并进 character_instances |
| `conversation_participants` | 成员与索引角色查询；替换为通用主体成员区间 |
| `agent_results` | 对话尝试结果存取；替换为 conversation_results |
| `thought_provenance` 与同步触发器 | 原 SQL 自动同步，当前 Python 无直接查询；来源并入 thoughts，文本清除更新同一行 |
| `meta` | migrate 重复版本及 lifecycle 启动记录；版本读 schema_migrations，进程状态读实际诊断 |
| 旧 SQL 曾建立又删除的 conversation_turns、situation_proposals、agent_proposals、reflection_tasks、reflection_results | 最新历史空库已无这些对象；新初始 SQL 不重播它们 |
| 原草案独立 community_state、character_availability、message_requests、conversation_contexts | 当前旧数据库没有这些表；按 05 的合并决定不创建 |

新表数量增加主要来自社群/玩家/实例身份、实际受众、精确输入与记忆来源，以及多人回应轮次。每个新增对象都有当前设计的实际消费者；没有空 Activity 表、通用事件总表、通用 Agent 结果总表或角色观察事实表。

### 6.2 字段、约束与实际查询确认

逐表核对已覆盖：主键及同范围 UNIQUE、直接引用复合外键、多态引用的正式事务校验、JSON/枚举 CHECK、非负计数、状态/时间一致性、领取租约与 approved 唯一性、成员重加入、有效别名/记忆边部分唯一性、查询顺序和来源版本。

现有查询入口已核对到 runtime/state/memory/search/reflection/trace Repository 及 provenance。新增查询入口对应第 4 节的正式服务与 02 的目标 Repository。实际索引依据采用 05 第 12 节，不复制同列索引。

SQLite 不会用单个外键验证 player/character 多态对象，也不会检查 JSON 里的业务身份。正式服务必须在同一事务读取真实对象并检查范围；能够明确指向单表的引用继续使用数据库约束。任务 3 用正式新 SQL 验证这些要求，任务 4—8 用实际调用路径验证可见性与消费。

## 7. 旧测试的处理清单

分类依据为测试实际验证对象与运行方式。同一文件可能包含多类测试；下面确认保留目标和具体删除内容，实施时逐项拆入 02 的新测试目录。

| 类别 | 处理原则 |
|---|---|
| 纯对象规则 | 保留有实际意义的规则，用新的正式类型重写；直接创建合法/非法领域对象属于正常验证 |
| 真实 SQLite | 保留持久化、外键、幂等、租约和回滚目标；使用新结构与正式 Repository |
| 业务提交 | 保留完整提交边界；调用正式服务，模型相关执行使用真实模型 |
| 模型调用 | 纯转换检查调用真实解析器；生成行为调用真实供应商；删除 Fake/Stub 预设结果 |
| 旧产品内容 | 删除旧剧情、旧版本、单角色限制、气泡和旧接口断言；保留真实人物资源的有效加载目标 |
| 模拟故障 | 删除注入异常和替换函数的实现；真实约束冲突、真实过期租约、正式关闭重启验证可达失败路径 |

具体文件表如下。

| 现有测试文件 | 函数定义数 | 实际类别 | 确认处理 |
|---|---|---|---|
| `test_agent_contracts.py` | 5 | 纯对象规则 | 保留调用身份、输出类型、预算与版本合法性，改用初始契约 |
| `test_agent_harness.py` | 10 | 纯对象规则、模型调用 | 保留预算与输出校验；删除 Stub 接口验收和脚本化网关执行 |
| `test_agent_routing.py` | 6 | 纯对象规则、模型调用 | 保留显式真实模型路由及能力；删除旧 Agent 属性猜测和 Fake 请求 |
| `test_conversation_runtime.py` | 7 | 业务提交、真实 SQLite、旧产品内容 | 保留幂等、审核与事务隔离；新 HTTP/真实 Agent 验证替换旧接口与缺失 OpenAPI 文件 |
| `test_conversation_sync.py` | 4 | 业务查询、旧产品内容、模拟故障 | 改为玩家会话可见增量查询；删除账号整体同步和 monkeypatch 替换 |
| `test_debug_capture.py` | 4 | 纯对象规则、模型调用 | 保留配置与真实文件捕获；删除 FakeCompletions/Fake 网关 |
| `test_domain_invariants.py` | 9 | 纯对象规则、旧产品内容 | 保留身份、序号、时间和合法状态；删除气泡与旧单角色结构断言 |
| `test_fault_injection.py` | 7 | 模拟故障 | 删除故障工具自身验收；真实回滚、过期与重启目标移入所属业务测试 |
| `test_harness_tool_loop.py` | 9 | 模型调用、纯对象规则 | 保留工具授权、预算、无进展及修正目标；真实模型和 memory_search 替换预设工具/网关 |
| `test_health.py` | 8 | 业务入口、模拟故障、旧产品内容 | 保留正式 live/ready 与生命周期检查；删除旧聚合 health 和 Stub/函数替换 |
| `test_identity_content_layout.py` | 4 | 纯对象规则、旧产品内容 | 保留完整资源和 Prompt 边界；删除旧 golden 版本与旧格式断言 |
| `test_identity_loader.py` | 5 | 纯对象规则 | 保留唯一格式、元数据和配置资源加载，删除双格式兼容目标，增加安装包资源验证 |
| `test_memory_foundation.py` | 4 | 纯对象规则、真实 SQLite | 保留有效期、归属、预置、日记与视图存储；改为实例身份 |
| `test_memory_search_and_sealing.py` | 8 | 真实 SQLite、业务查询、模拟故障 | 保留实际 FTS 与归段/失效/重建；新增精确可见来源，删除 monkeypatch 检索失败与默认启动初始化 |
| `test_migrations.py` | 7 | 真实 SQLite、旧产品内容 | 删除历史编号升级断言；验证新空库、约束、初始版本与真实失败回滚 |
| `test_model_gateway.py` | 10 | 纯对象规则、模型调用 | 保留配置和正式响应解析，真实 SDK 对象替代 FakeClient/FakeProviderError；真实请求另测 |
| `test_model_gateway_recovery.py` | 14 | 纯对象规则、模型调用、模拟故障 | 保留正式错误分类与期限规则；删除 Fake 供应商重试/截断产物，运行行为用真实供应商验证 |
| `test_observability_logging.py` | 4 | 纯对象规则、真实文件 | 保留日志过滤、轮转和配置路径，更新有效名称 |
| `test_observability_trace.py` | 2 | 纯对象规则 | 保留允许字段与私有原文过滤 |
| `test_recovery_contracts.py` | 6 | 纯对象规则 | 保留真实失败信息与恢复决定契约，删除旧字段 |
| `test_recovery_policy.py` | 9 | 纯对象规则 | 保留供应商/工具/审核分类和有限修正，更新取消暂停的新语义 |
| `test_reflection_artifact_normalizer.py` | 6 | 纯对象规则 | 保留标准化、证据/节点类型、合法 no_op；关系增加明确目标 |
| `test_reflection_batch.py` | 3 | 纯对象规则 | 保留稳定聚合、真实来源与合法 no_op |
| `test_reflection_graph_domain.py` | 9 | 纯对象规则 | 保留拓扑、依赖、不可变产物、维度范围与重复判断 |
| `test_reflection_node_input.py` | 11 | 纯对象规则 | 保留节点字段投影、证据资格、前置产物和 Prompt 职责；更新角色范围 |
| `test_reflection_persistence.py` | 4 | 真实 SQLite | 保留四类对象持久化和唯一性，新增完整快照恢复 |
| `test_reflection_review.py` | 7 | 纯对象规则 | 保留正式图审核、边界和材料预算，更新目标主体与精确来源 |
| `test_reflection_runtime.py` | 11 | 业务提交、真实 SQLite、模型调用 | 保留三图、partial、重试和消费目标；删除 Stub/CapturingAgent，真实模型执行 |
| `test_reflection_snapshot.py` | 3 | 纯对象规则 | 保留来源唯一及已有有效指纹规则，快照改为正式持久读取 |
| `test_runtime_acceptance.py` | 7 | 业务提交、模型调用、模拟故障 | 保留快照、租约代次、重启与失败释放目标；删除 Stub 和函数替换，改为新正式场景 |
| `test_runtime_data_tool.py` | 2 | 旧产品工具、真实 SQLite | 删除缺失外部工具调用；包内 CLI 初始化/检查/导出使用真实子进程和数据库 |
| `test_runtime_persistence.py` | 5 | 真实 SQLite | 保留记录往返、版本、领取与唯一结果目标；按新对象拆分 |
| `test_runtime_t1.py` | 8 | 业务提交、真实 SQLite、模拟故障 | 保留安静窗口、重复请求与重启；去掉 Stub 初始化与注入异常，增加玩家/受众隔离 |
| `test_runtime_t2.py` | 10 | 业务提交、真实 SQLite、旧产品内容、模拟故障 | 保留观察边界、原子准备和恢复；群聊拒绝/单任务限制删除，改为 SocialTurn 多任务 |
| `test_runtime_t3.py` | 16 | 业务提交、模型调用、旧产品内容、模拟故障 | 保留审核、沉默、重复、迟到及原子性；删除气泡、全局 Agent、旧整体版本失效与模拟产物 |
| `test_settings_toml.py` | 1 | 纯配置规则、旧产品内容 | 保留真实 TOML 解析；删除默认业务身份与剧情设置 |
| `test_state_relationship_domain.py` | 12 | 纯对象规则 | 保留状态历史、关系算法和资格，替换账号目标与剧情状态 |
| `test_state_repositories.py` | 3 | 真实 SQLite、纯对象规则 | 保留分类历史、关系/证据存取及主观关系描述，增加实例和目标隔离 |
| `test_state_scenarios.py` | 8 | 旧产品工具、真实 SQLite | 删除缺失工具和旧场景编号；有效状态/期限规则移入正式模块测试 |
| `test_task_dispatcher.py` | 4 | 纯注册规则、模拟执行 | 保留重复任务种类拒绝；FakeStore/RecordingHandler 替换为正式对话/反思队列 |
| `test_trace_outbox.py` | 7 | 真实 SQLite、业务提交、模拟故障 | 保留真实投递与去重；删除 Stub 和注入追踪失败，真实约束验证回滚 |
| `test_xiaojin_character_agent.py` | 6 | 模型调用、旧产品内容 | 保留真实模板角色与真实模型契约验证；删除 Fake 网关和旧版本/固定剧情绑定 |
| `test_xiaojin_regression_fixture.py` | 3 | 旧产品内容 | 删除旧编号和固定剧情回归断言；有效模板内容与真实身份验证进入新测试 |

辅助文件处理：`support_agent_context.py` 的正式对象构造按新类型整理进 fixtures；`support_xiaojin.py` 保留真实模板与输入构造所需部分，删除旧版本与固定剧情依赖；`support_faults.py` 删除 FaultPlan、PausableAgent、注入数据库/追踪等替身。时间相关规则通过正式接口的明确时间参数验证，避免为测试增加故障开关。

唯一现有 `real_smoke` 测试位于 `test_xiaojin_character_agent.py`，由环境变量选择运行，调用已配置真实模型。它只检查单角色单次调用，未覆盖新群聊，也未覆盖三种反思图的真实端到端提交；后续按 04 建立 `model` 标记和真实场景。

## 8. 进入任务 2 的依据

确认完成条件均已覆盖：第 2—3 节给出保留能力的真实入口、状态归属、事务和验证目标；第 4 节确认模块端口与依赖；第 5 节给出删除项及调用方替换；第 6 节说明每张表必要性和约束；第 7 节归类全部现有测试。未来 Activity 只保留设计契约，未进入本次代码清单。

下一步按任务 2 完成新工程入口、初始契约、唯一人物格式、真实模型配置和实例 Agent 的基础接口。旧实验数据库及原始参考资料继续保留。
