# 初始基线验收

基线版本 `0.1.0`。验收范围和成功标准来自 [A01—A32](../../docs/04-backend-baseline-and-acceptance.md#6-必须通过的场景)。以下对应真实测试；纯规则与存储测试直接使用正式对象、服务与临时 SQLite，模型场景调用真实供应商。

## 场景与证据

测试文件均位于 `tests/infrastructure/`。一项场景可以由业务规则、真实持久化及模型端到端的共同证据证明。

| 场景 | 证据文件与实际检查 |
|---|---|
| A01 空数据库与重复启动 | test_database_baseline、test_application_lifecycle：43 张登记表、版本 1、无默认对象、外键及重复初始化 |
| A02 跨社群独立实例 | test_final_acceptance：同一模板、共享玩家、不同社群的状态、关系、记忆、消息和任务范围独立 |
| A03 玩家交错输入 | test_message_perspective、test_social_planning：批次关联精确，同一受众轮次保留各自输入来源 |
| A04 多人选择与沉默 | test_social_planning：两名角色被选中、第三名保存人数限制原因，提及优先 |
| A05 同轮次真实调用 | test_agent_execution、test_application_lifecycle、test_http_api：独立身份与快照、真实工具和模型、分别提交 |
| A06 一个失败、另一个成功 | test_final_acceptance：缺失真实凭据导致首个任务失败，正式配置恢复后另一任务成功，新输入继续规划 |
| A07 全部不具备资格 | test_social_planning：正式可用状态设为 busy，轮次保存原因并正常完成，无模型任务 |
| A08 私有与公共轮次 | test_http_api：先完成公共回应，再完成指定角色的私有回应；另一玩家无法读取私有输入、回应和轮次 |
| A09 私有来源检索 | test_message_perspective：另一角色的实际 FTS 结果排除私有消息，重建后仍排除 |
| A10 历史成员区间 | test_database_baseline、test_message_perspective、test_memory_sealing：加入、离开、重加入按明确区间读取和归段 |
| A11 原快照不变 | test_conversation_commit：第一角色真实提交后第二角色继续使用原快照；恢复验证另见 test_process_recovery |
| A12 重复及内容冲突 | test_message_perspective、test_http_api：返回原消息；内容、受众或游标范围冲突被拒绝 |
| A13 重复与过期租约 | test_task_queue、test_conversation_commit、test_reflection_queue：旧代次不能续期，重复提交只保留一份结果与事实 |
| A14 暂停与归档 | test_task_lifecycle、test_social_planning：挂起保留快照，恢复继续，成员离开与归档取消并完成轮次 |
| A15 进程重启 | test_process_recovery：真实模型执行子进程被终止，到期后领取新租约代次并按原快照完成 |
| A16 精确段材料 | test_memory_sealing、test_conversation_commit：公共、角色私有消息与自身 Thought 分别归段，其他角色私有材料排除 |
| A17 段反思 | test_reflection_execution、test_character_facts：真实节点、产物、审核与摘要；正式角色事实验证明确目标、状态和来源重复消费 |
| A18 连续两批摘要 | test_reflection_execution：第一批覆盖至 3，第二批以原摘要及新段覆盖至 4，前驱内容精确传递，重复不新建图或摘要 |
| A19 真实记忆组织 | test_reflection_execution：记忆组织模型节点、真实图审核、实例事实、来源消费及禁止再次选择已消费摘要 |
| A20 未完成能力 | test_reflection_foundation、实际 registry 与 workflow：五种图定义，三种可执行消费者；日记、视图及自动触发保持未实现 |
| A21 取消检索能力 | test_final_acceptance：加载实际取消能力的资源，持久快照和模型工具列表为空，已实现检索工具的调用被授权规则拒绝 |
| A22 安装包运行 | tools/verify_installed.py：源码目录外安装，在空数据库初始化两名玩家与两个角色，两个真实角色完成回应；最终包资源及外键检查通过 |
| A23 新 HTTP | test_http_api：新路径、严格字段、公开响应排除内部信息，旧路径 404，内部诊断检查角色范围 |
| A24 追踪与普通日志 | test_trace_delivery、test_application_lifecycle、test_final_acceptance：追踪故障独立重试、来源链保存、普通日志排除私有正文和凭据 |
| A25 不同等待窗口 | test_message_perspective、test_conversation_commit：玩家只合并窗口内输入，角色提交直接建立 sealed 批次 |
| A26 气泡展示 | test_conversation_commit：一次完整产物仅保存一条消息和一个角色批次；持久化没有气泡序号或逐气泡触发 |
| A27 因果来源 | test_social_planning、test_conversation_commit：角色批次关联原轮次，不自动建立连续接话 |
| A28 世界与内部信息 | test_message_perspective、test_social_planning、test_reflection_context：客观参与者与消息、私有状态及记忆明确分组，角色范围隔离 |
| A29 原快照与 Thought 清除 | test_conversation_commit、test_process_recovery：快照恢复不变，Thought 清除正文后保留来源身份且反思不能再次取回原文 |
| A30 数据结构 | test_database_baseline、正式 SQL 和数据库说明一致性检查：实际字段与索引、外键约束、错误范围引用及事务回滚 |
| A31 原受众重新加入 | test_conversation_commit：玩家重加入不获得旧回应，角色离开再重加入仍不能用原任务提交，结果标记 expired |
| A32 真实迁移失败 | test_database_baseline：真实无效 SQL 回滚部分结构，不写入成功版本 |

## 模型配置与限制

对话与安装验证调用真实 DeepSeek。完整模型测试通过单独的实际设置文件，将 strong 路由指向真实 DeepSeek；角色 scope、工具、正式审核与业务规则保持一致。生产 model-registry.toml 的模型选择未修改。

原 strong 配置的 GLM 请求在本轮出现真实 120 秒超时和供应商重试。该次验证没有计为通过。模型选择属于用户配置，服务不会在超时后自动改换模型；成功运行仍依赖供应商响应及模型输出符合明确契约。

详细命令、当前结果与安装证据见 [任务 10 记录](../../docs/task-10-implementation.md)。功能限制见 [实现状态](implementation-status.md)。
