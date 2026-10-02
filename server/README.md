# Echo Commons Server

支持多名玩家与独立角色实例的后端。SQLite 保存业务状态；后台执行器调用真实模型，审核行动提议并提交消息与记忆。实际实现及限制见 [实现状态](docs/implementation-status.md)。

## 安装与检查

在 `server/` 目录运行：

```powershell
uv sync
uv run echo-commons init
uv run echo-commons inspect
uv run echo-commons serve
```

`init`（初始化）建立空数据库。`inspect`（检查）以只读方式查询数据库版本、实际记录数量和模型配置状态。`serve`（启动服务）按配置启动 HTTP 接口与后台执行器。

```powershell
uv run echo-commons init --example
uv run echo-commons export --output data/exports/community.sqlite3
uv run pytest tests/infrastructure -m "not model"
uv run pytest tests/infrastructure -m model
```

`--example` 创建两名玩家、两个使用同一模板的独立角色和一个群聊。也可以传入自己的 JSON 文件。`export`（导出）保存一致的完整数据库副本，包含私有消息和角色记忆；已有目标文件会被拒绝覆盖。示例使用方式见 [多人交流示例](examples/README.md)。

## 配置与人物资源

配置相对路径以设置文件所在目录为起点。默认设置为 `config/settings.toml`，真实模型配置为 `config/model-registry.toml`。真实凭据写入被 Git 忽略的 `config/model-secrets.toml`，格式见 `config/model-secrets.example.toml`。

小槿人物模板、声音风格、初始记忆、SQL、非秘密配置模板和多人示例随包提供。需要外部人物资源时，在 `[identity]` 中填写 `root`。指定目录缺失或格式无效会报告错误。

新数据库路径为 `data/echo-commons.sqlite3`。初始化不会创建默认人物或默认社群。模型调用前需要配置实际凭据；自动反思触发、活动玩法、`diary_compose` 和 `view_refresh` 的事实提交保持未实现。

## 安装包使用

在 `server/` 构建，然后在源码目录外的虚拟环境安装：

```powershell
uv build
uv pip install --python <虚拟环境中的python路径> dist/echo_commons_server-0.1.0-py3-none-any.whl
```

使用安装后的 `echo-commons` 命令，在选定的工作目录运行：

```powershell
echo-commons configure
echo-commons init --example
echo-commons inspect
echo-commons serve
```

`configure`（生成配置）复制内置的非秘密配置，拒绝覆盖已有文件。先在 `config/model-secrets.toml` 写入 `[credentials]` 及模型登记引用的实际凭据，再启动模型任务。可以通过 `echo-commons --settings <设置文件路径> serve` 指定另一份设置。所有相对配置路径以设置文件所在目录为起点；人物资源默认从安装包加载。

## 当前 HTTP 入口

```powershell
uv run echo-commons --settings config/settings.toml serve
```

接口清单和字段规则见 [HTTP 契约](../docs/01-backend-architecture.md#10-新-http-契约)。启动后 `/docs` 提供可操作的接口说明。消息和轮次读取必须提交 `player_id`，系统按真实成员区间和消息受众过滤结果。`/health/live` 检查进程存活，`/health/ready` 检查已初始化数据库和后台执行状态。

`/internal/` 提供本地开发诊断：上下文需要 `community_id` 和路径中的角色、任务标识；反思运行需要 `community_id`、`character_id`；追踪按关联标识查询。公开响应只包含明确的展示字段。CORS（浏览器跨站访问规则）来源由 `[server].cors_origins` 配置。

## 设计与实现记录

- [架构与运行模型](../docs/01-backend-architecture.md)
- [目标文件结构](../docs/02-backend-file-structure.md)
- [数据库设计](../docs/05-database-design.md)
- [接口、开发命令与安装验证](../docs/task-09-implementation.md)
