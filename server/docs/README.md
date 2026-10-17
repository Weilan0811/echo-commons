# 后端文档

版本 0.1.0。本目录按设计、参考和指南组织后端文档：设计说明业务规则与模块职责，参考记录实际契约，指南说明开发和使用。实现范围、验证结果、设计差距与开发顺序统一见 [状态](status.md)。阅读本目录无需依赖历史重构资料。

项目整体阶段与前后端协作安排见 [项目推进计划](../../docs/01-project-roadmap.md)。本目录负责后端设计、接口和实现状态；前端选型与页面规划由前端文档负责。

已确认的业务约定由下方正式设计维护。已有实例重置、主动开口、话题卡与事件卡的待办范围见 [状态](status.md)。

## 理解整体设计

| 文档 | 主要问题 |
|---|---|
| [系统与运行模型](design/system.md) | 平台对象、模块边界、群聊与反思完整运行 |
| [对象生命周期](design/object-lifecycles.md) | 状态分别属于谁、谁改变状态、任务与结果如何关联 |
| [身份与社群](design/identity-and-communities.md) | 模板和实例、成员区间、世界时间 |
| [自定义人物创作](design/custom-character-authoring.md) | 三阶段设定、四套提示、采访与人设校准、候选审核、固定资源及实例创建 |
| [会话与社会轮次](design/conversation-and-social.md) | 窗口、参与选择、任务、受众与提交 |
| [玩家 API 与成员操作](design/player-api.md) | 玩家范围、最新与历史分页、阅读位置、成员版本和重复请求 |
| [图像资产与生成](design/image-assets.md) | 用户图片、公共生图提示、APIMart 任务、业务引用与文件存储 |
| [HTTP 与 SSE 实时通信](design/realtime-communication.md) | 业务事件、玩家投影、提交后推送、连接与恢复位置 |
| [观察与上下文](design/perspective-and-context.md) | 客观信息、自身认识、历史、记忆与冻结输入 |
| [状态与关系](design/character-state-and-relationships.md) | 期限、资格、三维公式、重复与版本 |
| [记忆](design/memory.md) | 原始来源、摘要压缩、长期事实与认知、版本及检索 |
| [四种反思执行图](design/reflection/README.md) | 摘要、事实审核、认知形成及常驻表达的节点与提交 |
| [Agent 与模型](design/agents-and-models.md) | 身份、工具循环、预算、路由和重试 |
| [角色提示契约](design/character-prompt-contracts.md) | 原对话和反思完整文字、判断细则、示例及必要扩展 |
| [任务执行](design/task-execution.md) | 队列、租约、额度、生命周期和恢复 |
| [错误分类、重试与恢复](design/errors-and-recovery.md) | 已核实的迁移差距、完整恢复决定、修正提示及诊断恢复要求 |
| [持久化](design/persistence.md) | 数据对象、事务、约束、迁移和备份 |
| [可观察性](design/observability.md) | 日志、追踪、捕获和诊断 |
| [角色活动与局内会话](design/activity-integration.md) | 游戏边界、局内协调决策、调用策略与经历保存 |
| [架构决定](adr/README.md) | 长期设计背景、取舍和影响 |

四图分别展开 [segment_reflect](design/reflection/segment-reflect.md)、[continuity_compress](design/reflection/continuity-compress.md)、[memory_organize](design/reflection/memory-organize.md)、[view_refresh](design/reflection/view-refresh.md)。日记旧设计保留于 [diary_compose](design/reflection/diary-compose.md)，Demo 暂缓开发。先看 [共同执行模型](design/reflection/execution-model.md)。

## 查阅实际契约

- [HTTP](reference/http-api.md)：全部路径、字段、错误和请求例子，附 [OpenAPI](reference/openapi.json)。
- [游戏接口](reference/game-api.md)：玩法目录、大厅、真人参与、局势与行动机会、回执和正式历史。
- [SSE 事件](reference/event-api.md)：实时通知、初始位置、恢复和控制事件，附 [事件数据契约](reference/event-data-schema.json)。
- [本地管理接口](reference/management-api.md)：对象发现、任务与记忆诊断、反思操作和范围化材料导出。
- [配置](reference/configuration.md)：全部设置、路径、模型和凭据，附 [Settings schema](reference/settings-schema.json)。
- [人物资源](reference/character-resources.md)：全部格式和完整合法作者示例。
- [数据库](reference/database-schema.md)：实际字段、主外键、索引、CHECK 与完整 DDL。
- [源码导航](reference/source-map.md)：按模块定位类型、函数及文件。

## 开发与接入

- [本地开发](guides/local-development.md)：安装、空库、示例、启动、导出与安装包。
- [前端接入](guides/frontend-integration.md)：创建顺序、身份、初次同步、消息事件、恢复和图像资产使用。
- [故障与恢复](guides/debugging-and-recovery.md)：配置、模型、审核与恢复定位。
- [扩展指南](guides/extending-the-platform.md)：模板、工具、节点、消费者及任务。
- [验证指南](guides/verification.md)：A01—A34、真实证据与后续必要断言。

设计是生成和检查代码的依据。参考与设计冲突时，在状态登记差异，审核后修改相应实现。
