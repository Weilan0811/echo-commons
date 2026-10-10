# 后端验证指南

基线版本 `0.1.0`。下表保留长期验证目标和现有证据入口。设计成功标准由 [系统设计](../design/system.md) 及各专项设计规定。表中测试证明其实际断言，不能证明尚未检查的设计规则。模型场景使用真实供应商。

## 场景与证据

测试文件均位于 `tests/infrastructure/`。一项场景可以由业务规则、真实持久化及模型端到端的共同证据证明。

历史私有消息由 `historical_messages.py` 准备真实数据库记录及关联的批次和索引，专用于已有数据与任务的验证；新发送场景通过正式接口创建独立会话，不提供指定受众输入。

| 场景 | 证据文件与实际检查 |
|---|---|
| A01 空数据库与重复启动 | test_database_baseline、test_application_lifecycle：登记表、当前迁移版本 4、无默认对象、外键及重复初始化 |
| A02 跨社群独立实例 | test_final_acceptance：同一模板、共享玩家、不同社群的状态、关系、记忆、消息和任务范围独立 |
| A03 玩家交错输入 | test_message_perspective、test_social_planning：批次关联精确，同一受众轮次保留各自输入来源 |
| A04 多人选择与沉默 | test_social_planning：两名角色被选中、第三名保存人数限制原因，提及优先 |
| A05 逐次群聊真实调用 | test_agent_execution、test_application_lifecycle、test_http_api：独立身份与快照、真实工具和模型、逐次提交；新安排观察刚提交的消息 |
| A06 一个失败、另一个成功 | test_final_acceptance：缺失真实凭据导致首个任务失败，正式配置恢复后另一任务成功，新输入继续规划 |
| A07 全部不具备资格 | test_social_planning：正式可用状态设为 busy，轮次保存原因并正常完成，无模型任务 |
| A08 群聊与独立私聊轮次 | test_http_api：先完成群聊回应，再完成独立私聊会话中的回应；另一玩家无法读取私聊输入、回应和轮次。test_management_api 验证历史私有轮次继续按原受众提交 |
| A09 私有来源检索 | test_message_perspective：另一角色的实际 FTS 结果排除历史私有消息，重建后仍排除 |
| A10 历史成员区间 | test_database_baseline、test_message_perspective、test_memory_sealing：加入、离开、重加入按明确区间读取和归段 |
| A11 原快照不变 | test_conversation_commit：升级前双角色任务真实提交后继续使用旧快照；test_social_continuation：新安排读取新发言及根玩家输入；恢复验证另见 test_process_recovery |
| A12 重复及内容冲突 | test_message_perspective、test_http_api：返回原消息；正文、提及、历史私有标识或游标范围冲突被拒绝；新发送拒绝 visibility 和 recipients 字段 |
| A13 重复与过期租约 | test_task_queue、test_conversation_commit、test_reflection_queue：旧代次不能续期，重复提交只保留一份结果与事实 |
| A13.1 写事务等待与心跳 | test_task_transaction_times：真实 SQLite 写入占用与线程同步验证心跳之后的提交、续期和恢复时间，等待后的租约过期、终态续期与重复保存；真实模型场景验证完整生成结果。tools/verify_reflection_recovery.py 在数据库副本通过正式入口恢复历史失败分支，核对成功节点复用与重复审核 |
| A14 暂停与归档 | test_task_lifecycle、test_social_planning：挂起保留快照，恢复继续，成员离开与归档取消并完成轮次 |
| A15 进程重启 | test_process_recovery：真实模型执行子进程被终止，到期后领取新租约代次并按原快照完成 |
| A16 精确段材料 | test_memory_sealing、test_conversation_commit：公共、历史私有消息与自身 Thought 分别归段，其他角色私有材料排除 |
| A17 段反思 | test_reflection_execution、test_character_facts：真实节点、产物、审核与摘要；正式角色事实验证明确目标、状态和来源重复消费 |
| A18 连续两批摘要 | test_reflection_execution：第一批覆盖至 3，第二批以原摘要及新段覆盖至 4，前驱内容精确传递，重复不新建图或摘要 |
| A19 真实记忆组织 | test_reflection_execution：记忆组织模型节点、真实图审核、实例事实、来源消费及禁止再次选择已消费摘要 |
| A20 未完成能力 | test_reflection_foundation、实际 registry 与 workflow：五种图定义，三种可执行消费者；正式内部入口安排后由后台执行。自动封段和材料扫描调度、日记与视图尚未接入 |
| A21 取消检索能力 | test_final_acceptance：加载实际取消能力的资源，持久快照和模型工具列表为空，已实现检索工具的调用被授权规则拒绝 |
| A22 安装包运行 | tools/verify_installed.py：源码目录外安装，在空数据库初始化两名玩家与两个角色，两个真实角色完成回应；最终包资源及外键检查通过 |
| A23 新 HTTP | test_http_api：新路径、严格字段、公开响应排除内部信息，旧路径 404，内部诊断检查角色范围 |
| A24 核心记忆 | test_core_memory_refresh：真实页面与原文来源、未读范围、预算不足、重复请求、来源失效及模式限制；真实模型验证 300 字符配置和完整有效范围 `no_op` 清除视图而保留长期页。tools/verify_core_memory.py 使用实际数据库的只读备份重建，并保留两个角色各五种对话的前后输出供内容核对 |
| A24 追踪与普通日志 | test_trace_delivery、test_application_lifecycle、test_final_acceptance：追踪故障独立重试、来源链保存、普通日志排除私有正文和凭据 |
| A25 不同等待窗口 | test_message_perspective、test_conversation_commit：玩家只合并窗口内输入，角色提交直接建立 sealed 批次 |
| A26 气泡展示 | test_conversation_commit：一次完整产物仅保存一条消息和一个角色批次；持久化没有气泡序号或逐气泡触发 |
| A27 因果来源 | test_social_planning、test_conversation_commit：角色批次关联原轮次和新链触发，只消费一次；旧角色批次不补建触发 |
| A28 世界与内部信息 | test_message_perspective、test_social_planning、test_reflection_context：客观参与者与消息、私有状态及记忆明确分组，角色范围隔离 |
| A29 原快照与 Thought 清除 | test_conversation_commit、test_process_recovery：快照恢复不变，Thought 清除正文后保留来源身份且反思不能再次取回原文 |
| A30 数据结构 | test_database_baseline、正式 SQL 和数据库说明一致性检查：实际字段与索引、外键约束、错误范围引用及事务回滚 |
| A31 原受众重新加入 | test_conversation_commit：玩家重加入不获得旧回应，角色离开再重加入仍不能用原任务提交，结果标记 expired |
| A32 真实迁移失败 | test_database_baseline：真实无效 SQL 回滚部分结构，不写入成功版本 |
| A33 SSE 实时通信 | test_realtime：真实 HTTP 连接、多玩家广播、范围过滤、成员区间、已读、暂停、断线补充、进程终止后恢复、事件清理、事务回滚及慢连接释放；真实模型验证角色发言与沉默的轮次完成通知。tools/verify_realtime_installed.py 验证安装后的迁移与实际推送 |
| A34 指定范围清理 | test_maintenance：真实 SQLite 与 HTTP 验证预览、暂停、回复与记忆任务、暂停后的运行调用、人物资源及玩家引用、向量处理与缺少配置的实际失败、追踪投递、范围外消息与全文索引保留、事务回滚、重复执行、全局序号及删除社群后的 SSE 关闭。测试配置显式使用不存在的独立凭据路径 |

## 最近验证与质量边界

最近测试数量、实际路由、安装验证范围和现有边界统一见 [实现状态](../status.md#3-验证范围)。上表列出可复用的验证场景和证据入口，各项历史证据不表示最近一次已全部重新执行。

模型自行决定是否发言和查询记忆。两项查询模型测试接受合法沉默，以及没有调用工具的合法回复；它们核对真实身份、输出契约、停止原因和结果恢复。实际查询从模型捕获读取真实工具调用与返回材料，逐项核对来源、版本和私人范围；不要求调用次数或回答某个固定词。正式检索工具的独立执行测试继续验证能力与范围。

`test_management_api` 使用正式服务、真实 SQLite 和 HTTP 验证对象发现、分页游标范围、消息受众、任务关联、追踪归属、封段预算与重复请求、失败队列恢复和范围化导出。模型场景覆盖实际发言与内心清除后的管理投影，以及通过 HTTP 安排三种反思、后台节点执行、记忆详情和导出。模型选择长期页和实体的数量可变化；已有结果的身份与来源必须正确。

长期记忆流程执行、事实保存和来源隔离通过技术验证，不等于整理内容已经通过质量验收。真人材料评价需要检查：关键事件和约定是否保留、陈述归属是否明确、感受是否忠于材料、长期页是否便于以后使用、实体及关系是否有来源。认识刷新接入后沿用相同材料标准，并验证自身专项规则。

## 执行命令与证据含义

在 server 目录运行：

```powershell
uv run pytest -m "not model"
uv run pytest -m model
uv run python tools/build_file_reference.py --check
uv run python tools/build_database_reference.py --check
uv run python tools/build_contract_reference.py --check
```

模型测试读取真实登记和密钥；可使用 `ECHO_COMMONS_TEST_SETTINGS` 指定独立设置路径。记录所用路由、供应商、时限及实际成功或失败。没有凭据时不能用预设回复补足验证。

图像专项为 `test_image_assets.py`，使用真实 Pillow 图片、HTTP 文件上传、SQLite 和文件读取。安装包图像验证执行 `tools/verify_image_assets_installed.py`，脚本自行建立临时数据库、资产目录及缺失凭据路径，覆盖随包资源和上传、裁剪、读取、删除。图像供应商验收需在独立环境配置 APIMart 凭据，分别验证三种用途、同编号重复请求、实际尺寸、查询期间重启及下载保存；任务申请只读取公开人物材料和明确场景输入。

安装验证先构建 wheel，再在源码目录外的虚拟环境安装并执行 tools/verify_installed.py；它读取真实配置并会请求模型。完整命令及资源范围见 [本地开发](local-development.md)。

测试增加时使用正式对象、服务、真实 SQLite 和实际失败：过期租约、业务成员变化、真实约束冲突及进程关闭。正常对象构造允许明确时间参数，不替换函数制造预设执行。

## 持续保留的业务验证

| 设计范围 | 必要断言 |
|---|---|
| 原始提示和必要扩展 | 正式对话与六类反思投影逐字保留固定正文、例子及工具/修正文字；发送者、target、沉默等必要差异逐项列明 |
| 人物创作与采访 | 新候选冻结实际 2.0 提示和依据，日常契约不进入采访；真实检查第三人称故事、寡言与外向人物、过去空白、隐藏事实、硬性限制与明确冲突；保存候选、正式接受记录和调用量 |
| 反思节点投影 | 正式 NodeInput 和模型消息符合各节点的字段选择；完整存储快照不能导致模型获得无关状态、关系、记忆或 voice |
| 自身历史 Thought | 实际 ConversationContext 包含对应自身历史 Thought，其他角色隔离、预算及清除后缺失 |
| continuity NoOp | 冻结批次不能 approved NoOp，消费和覆盖不被错误结束 |
| 租约与图恢复 | 节点过期租约使用冻结输入，新代次拒绝旧结果；正式调度重新启动未形成审核结果的 failed 图，复用成功产物；partial 补充恢复继续未实现 |
| 状态版本与时间 | 提交事务读取最新类别版本并正确追加；原替换规则、时间顺序、有效期和拒绝条件保留，不新增模型候选版本字段 |
| 关系算法和重复来源 | 原三维数值、资格和步长一致；多目标分组、原候选来源身份及正式重复路径逐项验证 |
| 参数与契约 | 省略及显式路径基准一致，错组字段被拒绝；SQL 和类型一致；system、intent 按原实际支持范围核查 |

逐字验证使用正式资源、正式领域对象和正式投影器；动态身份和时间检查真实来源，不比较模型随机生成的措辞。针对群聊和飞行棋的设计核查还需要验证：聊天参与决定独立于玩法行动机会，未来活动采用专用输入和提交入口。活动、日记和视图当前继续保持未实现。

以上通过实际入口验证，作为后续实现的持续检查。真实模型场景记录实际选择和结果，固定正文逐字比较与业务断言继续保留。当前结果见 [实现状态](../status.md#3-验证范围)。文档链接、结构及参考检查证明资料可以读取和实际契约一致，内容质量需要真人材料及专项评价。

## 逐次群聊专项

`test_social_continuation` 验证规则排序、原成员区间、输入幂等、收集窗口、暂停时插话、真实准备失败的任务预算及公开和管理查询。三个真实模型场景验证连续三条发言、实际供应商请求中的根玩家问题与前一条新消息、全部候选实际沉默，以及模型请求进行期间玩家插话后旧结果被拒绝。`test_process_recovery` 验证原任务恢复后继续创建后续安排，计数和原快照保持正确。`test_conversation_commit` 在真实版本 9 数据库上执行迁移，再用真实模型完成旧双角色任务。
