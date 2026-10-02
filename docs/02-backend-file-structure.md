# 后端文件结构与职责

基线版本：`0.1.0`。当前实现已按业务模块组织。完整文件与实际入口见 [后端文件导航](../server/docs/file-structure.md)，具体职责见 [模块索引](../server/docs/modules/README.md)。本文件说明长期目录组织与查找方法。

## 顶层目录

路径相对 `server/src/echo_commons/`。发行名称为 `echo-commons-server`；Python 包保留 `echo_commons`，明确限定项目代码与安装资源。

| 目录 | 负责内容 |
|---|---|
| app | 设置、唯一组合根、HTTP 路由组装、生命周期、开发命令与内部诊断 |
| modules | 按业务管理纯规则、流程、数据访问、接口与具体任务 |
| agents | 正式输入输出契约、角色 Agent 与模型工具循环 |
| execution | 任务分派、共享预算、租约、恢复和后台执行器 |
| infrastructure | SQLite 连接及 SQL、真实模型 SDK、日志与追踪 |
| shared | ActorRef、明确范围与公共错误 |
| resources | 完整人物资源、非秘密配置模板和显式示例 |

## 业务模块

| 模块 | 负责内容 |
|---|---|
| communities | 玩家登记、社群身份、成员资格、时间与生命周期 |
| characters | 人物模板、独立实例、可用状态、自身状态、关系认识与能力 |
| conversations | 会话、历史成员区间、权威消息、输入、对话任务与提交 |
| social | SocialTurn、ParticipationDecision、轮次来源、规划及完成 |
| perspective | 按观察者、成员区间与消息上限包装客观世界材料 |
| memory | 私有记忆、Thought、精确来源、归段、摘要、组织和检索 |
| reflection | 固定图、来源快照、节点、产物、审核及事实提交 |

在模块内部，domain 保存标准库纯规则，services 保存业务编排，repositories 保存持久化，api 保存明确请求与响应，tasks 保存该业务的任务准备、执行、审核与提交。单一职责可以使用独立文件，已有多个职责的模块使用相应目录。contracts 定义跨模块实际使用的读取或事实写入端口。

## 依赖与拓展

app/composition.py 明确注入具体实现，Application 在同一组合文件保存实际服务和资源。app/development.py 通过正式业务入口初始化显式示例，CLI 不定义默认世界。各包初始化文件不聚合重复导出。

perspective 提供可见世界事实，characters 提供自身状态与主观关系，memory 提供经历和长期信息；具体任务组装不可变输入。Agent 输出行动提议，通过所属模块提交权威事实。跨模块服务调用明确端口，并使用发起业务服务持有的同一短事务。

未来活动加入 modules/activities，管理活动状态、行动机会和 ActivityTask。活动任务拥有独立队列与提交，复用观察、记忆及执行基础；本次没有活动实现或活动表。

## 工程与资源

server/pyproject.toml 和 uv.lock 管理发行、依赖与命令；config 保存用户本地配置与被忽略的密钥；docs 保存实际说明；examples/README.md 说明真实多人示例；tests/infrastructure 保存真实验证；tools 保存安装和文档一致性检查。

人物与声音风格从 resources/identity 加载，示例从 resources/examples/group.json 加载，非秘密配置从 resources/config 加载，SQL 从 infrastructure/database/sql 加载。源码目录外的安装加载规则见 [服务说明](../server/README.md)。
