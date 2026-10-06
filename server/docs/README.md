# 后端文档

版本 0.1.0。本目录按设计、参考和指南组织后端文档：设计说明业务规则与模块职责，参考记录实际契约，指南说明开发和使用。实现范围、验证结果、设计差距与开发顺序统一见 [状态](status.md)。阅读本目录无需依赖历史重构资料。

项目整体阶段与前后端协作安排见 [项目推进计划](../../docs/01-project-roadmap.md)。本目录负责后端设计、接口和实现状态；前端选型与页面规划由前端文档负责。

新近讨论且尚未实现的方案见 [设计草案](design-drafts/README.md)，包括自定义角色与重置、运行模式与初始记忆、角色接话，以及主动开口、话题卡和事件卡。草案分别标明已确认方向、建议与待决问题；旧设计来源已保存，具体契约确定后再写入所属正式设计。

## 理解整体设计

| 文档 | 主要问题 |
|---|---|
| [系统与运行模型](design/system.md) | 平台对象、模块边界、群聊与反思完整运行 |
| [对象生命周期](design/object-lifecycles.md) | 状态分别属于谁、谁改变状态、任务与结果如何关联 |
| [身份与社群](design/identity-and-communities.md) | 模板和实例、成员区间、世界时间 |
| [自定义人物创作](design/custom-character-authoring.md) | 三阶段设定、四套提示、采访与人设校准、候选审核、固定资源及实例创建 |
| [会话与社会轮次](design/conversation-and-social.md) | 窗口、参与选择、任务、受众与提交 |
| [玩家 API 与成员操作](design/player-api.md) | 玩家范围、最新与历史分页、阅读位置、成员版本和重复请求 |
| [观察与上下文](design/perspective-and-context.md) | 客观信息、自身认识、历史、记忆与冻结输入 |
| [状态与关系](design/character-state-and-relationships.md) | 期限、资格、三维公式、重复与版本 |
| [记忆](design/memory.md) | 来源、归段、摘要、长期页、实体与检索 |
| [四种反思图](design/reflection/README.md) | 四图拓扑、节点契约、审核、失败与例子 |
| [Agent 与模型](design/agents-and-models.md) | 身份、工具循环、预算、路由和重试 |
| [角色提示契约](design/character-prompt-contracts.md) | 原对话和反思完整文字、判断细则、示例及必要扩展 |
| [任务执行](design/task-execution.md) | 队列、租约、额度、生命周期和恢复 |
| [错误分类、重试与恢复](design/errors-and-recovery.md) | 已核实的迁移差距、完整恢复决定、修正提示及诊断恢复要求 |
| [持久化](design/persistence.md) | 数据对象、事务、约束、迁移和备份 |
| [可观察性](design/observability.md) | 日志、追踪、捕获和诊断 |
| [活动接入](design/activity-integration.md) | ActivityTask、合法操作与聊天并行 |
| [架构决定](adr/README.md) | 长期设计背景、取舍和影响 |

四图分别展开 [segment_reflect](design/reflection/segment-reflect.md)、[continuity_compress](design/reflection/continuity-compress.md)、[memory_organize](design/reflection/memory-organize.md)、[view_refresh](design/reflection/view-refresh.md)。日记旧设计保留于 [diary_compose](design/reflection/diary-compose.md)，Demo 暂缓开发。先看 [共同执行模型](design/reflection/execution-model.md)。

## 查阅实际契约

- [HTTP](reference/http-api.md)：全部路径、字段、错误和请求例子，附 [OpenAPI](reference/openapi.json)。
- [本地管理接口](reference/management-api.md)：对象发现、任务与记忆诊断、反思操作和范围化材料导出。
- [配置](reference/configuration.md)：全部设置、路径、模型和凭据，附 [Settings schema](reference/settings-schema.json)。
- [人物资源](reference/character-resources.md)：全部格式和完整合法作者示例。
- [数据库](reference/database-schema.md)：实际字段、主外键、索引、CHECK 与完整 DDL。
- [源码导航](reference/source-map.md)：按模块定位类型、函数及文件。

## 开发与接入

- [本地开发](guides/local-development.md)：安装、空库、示例、启动、导出与安装包。
- [前端接入](guides/frontend-integration.md)：创建顺序、身份、消息和轮次轮询。
- [故障与恢复](guides/debugging-and-recovery.md)：配置、模型、审核与恢复定位。
- [扩展指南](guides/extending-the-platform.md)：模板、工具、节点、消费者及任务。
- [验证指南](guides/verification.md)：A01—A32、真实证据与后续必要断言。

设计是生成和检查代码的依据。参考与设计冲突时，在状态登记差异，审核后修改相应实现。
