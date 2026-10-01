# 任务 2：新工程入口与初始契约

完成日期：2026-10-01  
状态：阶段完成；完整聊天、持久任务和反思尚待后续任务接入  
依据：[实施计划](03-backend-implementation-plan.md#4-任务-2新工程入口与初始契约)、[目标结构](02-backend-file-structure.md)

## 1. 完成内容

- 发行包改为 `echo-commons-server`，全部有效源码使用 `echo_commons` 包名。删除旧顶层 main/config 和旧包转发导出，入口归 `app/main.py`、`app/cli.py`、`app/settings.py`。
- 建立纯领域引用 `ActorRef`、`CommunityScope`，明确玩家和角色种类。建立 `ContextSnapshot` 格式 1，将自身信息、客观观察、记忆、环境、动作范围和来源版本分别保存。
- 调用契约明确社群、实例、任务和业务来源，检查快照身份、快照格式、输出契约与工具权限一致性。
- 通用输出注册表由正式模型类型解析指定契约，角色发言使用 `character_message.v1`。执行结果不再把所有输出限制为角色发言。
- CharacterAgent 使用明确的 descriptor（身份与能力描述）和 TaskRouting（任务模型选择规则），删除缺失属性时的动态猜测。
- 正式模型适配移入 `infrastructure/models/`，保留真实供应商请求、流式标准化、错误分类和有限重试。ModelRequest 只接受 `output_contract`；删除重复 `output_schema` 和 legacy 解析。
- 删除 Stub、Fake 网关、默认角色 factory 和模拟后端选择。真实模型客户端由 SDK 直接建立，并提供明确关闭操作。
- 模板类型与加载器归 `modules/characters/templates/`。人物资源完整移入包内 `resources/identity/blueprints/`，唯一格式编号为 1，内容版本为 `0.1.0`。外部资源被明确指定后，缺失即报告错误。
- 保留小槿的真实正文、voice、相处方式、能力与四份预置记忆。预置自身引用为 `self`，创建实例时再解析真实实例身份。模板能力参数以 JSON 文本保存，读取返回独立对象，避免修改查询结果影响共享模板。
- 配置删除默认玩家、角色、会话与旧剧情设置；数据库指向 `server/data/echo-commons.sqlite3`。保留用户模型选择和本地密钥，模型后端只使用 `openai_compatible`。
- 移动模型使用的日志与捕获模块；保留明确启用的捕获行为。
- 重建依赖锁文件。任务 1 已确认无运行消费者的 numpy、onnxruntime、sqlite-vec、tokenizers 提前删除，避免为新开发环境安装闲置组件。
- 删除 20 份依赖模拟实现、函数替换或故障注入的旧测试及 `support_faults.py`。这些文件的有效验证目标已在任务 1 记录，将随所属正式模块重新实现；不把删除测试当作测试通过。

## 2. 真实验证

工作目录为 `server/`。

| 检查 | 结果 |
|---|---|
| `uv sync`、`uv lock --check` | 新发行包和依赖环境建立，锁文件一致 |
| `uv run pytest tests/infrastructure/test_initial_baseline.py` | 12 项通过，无警告；检查真实模板、唯一格式、缺失资源、配置、契约、身份和序列化 |
| 本阶段新/迁移模块的 `ruff check` 与 `ruff format` | 通过；范围包括 app、shared、models、日志/捕获、模板、Agent 基础契约与角色包装、新测试 |
| `uv run python -m echo_commons.app.cli inspect` | 正式读取配置和模板，输出新数据库路径、xiaojin 模板与真实模型配置可用状态；不输出凭据 |
| `uv build --wheel` | 成功构建 `echo_commons_server-0.1.0` |
| wheel 安装至独立临时目录，源码目录外使用隔离解释器导入 | 完整小槿模板与 voice 成功加载，格式/包版本正确；真实网关可导入 |
| 全部源码 AST 解析及旧包引用扫描 | 151 个源码文件语法有效，源码没有 `echo_server` 引用 |
| 新数据库与旧数据保护 | 未创建新数据库；旧数据与密钥未修改；构建和独立安装目录已自动清理 |

缺少凭据验证调用正式 Gateway，它在真实配置边界返回 `provider_not_configured`，不会请求供应商或生成模拟回应。本阶段尚未验证模型生成，真实生成按任务 6、8 和最终验收执行。

## 3. 自行审核结论

任务 2 的基础能力可以独立导入与验证，不需要启动 Worker、初始化数据库或调用模型。资源只有一个有效目录，打包使用包目录自动包含资源，安装后完整读取已经实测。配置没有业务默认身份；正式模型配置不含替身路径。

当前完整系统仍处于结构改造过程：旧 Runtime、存储、上下文组装和剩余旧测试将在任务 3—10 替换，不能用它们验证新业务。新 HTTP 入口目前只提供真实存活检查，CLI 的 inspect 目前检查配置与模板；完整业务接口、数据库检查和初始化/导出在任务 9 接入。

旧反思算法和未完成定义仍保留在待适配源码中。本阶段没有实现 diary_compose、view_refresh 或活动功能。三种反思图的完整调用链将在任务 8 使用新契约接入。

## 4. 阶段编辑记录

本记录与本阶段源码、资源、配置、测试和锁文件在同一独立提交中保存。查看本阶段提交的 Git diff（编辑差异）可以单独审查全部修改；前一提交保留重建前的算法与测试依据。

后续任务 3 建立新身份模型、正式 Repository 和初始 SQL。新 SQL 的真实空库与约束验证完成后，删除旧 16 份迁移。
