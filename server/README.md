# Echo Agent Service

本目录是《回响》的本地 Python 服务。它是权威状态的唯一持有者，Unity 客户端不得绕过 HTTP API 直接访问存储。

当前服务提供对话、反思图运行、模型调用和运行诊断能力。HTTP 入口包括 `GET /health`、`POST /message/send`、`GET /message/sync` 和本地反思诊断接口。工程文档入口：

- [后端整体实现架构](docs/architecture.md)
- [后端实现状态](docs/implementation-status.md)
- [Conversation 模块设计](docs/modules/conversation.md)
- [Architecture Decision Records](docs/adr/README.md)

全局设置在 `config/settings.toml`，按服务、存储、身份、Worker、对话、反思、模型路径和诊断分类。修改后重启服务生效；相对路径以该文件所在目录为起点。`conversation.generation` 与 `reflection.generation` 可分别设置 `temperature`、`top_p` 和 `max_output_tokens`，留空则使用所选模型的参数。Python 调用方仍可通过 `Settings(...)` 为独立运行指定路径和参数。

模型路由和各模型默认参数由 `config/model-registry.toml` 配置。密钥只填写到本地且被忽略的 `config/model-secrets.toml`；没有密钥时使用 Stub，不会发起远端调用。模型边界和请求转换见 [Model Gateway](docs/modules/model-gateway.md) 与 [Agent Runtime](docs/infrastructure/agent-runtime.md)。

Identity 运行时资源以 `config/identity/` 为唯一来源，服务启动时会校验 manifest 和版本化 Markdown；需要使用外部资源时，修改 `settings.toml` 的 `identity.root`。外部目录存在但校验失败时服务拒绝启动，只有目录不存在时才回退到内置资源。

本地密钥文件只需要保存 credential 引用，不重复登记模型：

```toml
[credentials]
deepseek = "your-deepseek-key"
dashscope = "your-dashscope-key"
```

当前代码按以下职责分层：

```text
src/echo_server/
├─ api/             # HTTP DTO、路由和依赖注入
├─ runtime/         # Conversation、Reflection、Memory 和任务执行
├─ agents/          # Echo-native Contract、Harness 和 Agent 实现
├─ domain/          # 纯领域对象和确定性规则
├─ services/        # Model、Memory、Identity 等共享能力
├─ store/           # SQLite、migration 和 Repository
└─ observability/   # 日志、Trace 查询和 Debug Capture
```

模块边界和依赖关系以 [后端架构](docs/architecture.md) 为准。

## 环境管理

后端统一使用 `uv`：

- `.python-version` 固定开发解释器为 Python 3.11；
- `pyproject.toml` 声明直接依赖和开发依赖组；
- `uv.lock` 锁定完整依赖图，应纳入版本管理；
- `.venv/` 由 `uv sync` 自动生成，不纳入版本管理；
- 不使用 `pip install` 直接修改项目环境。

常用命令：

```powershell
uv sync --group dev
uv run pytest
uv run ruff check .
uv run uvicorn echo_server.main:app --host 127.0.0.1 --port 8765 --reload
```

### 本地对话工作台

页面和脚本只保存在仓库根目录被 Git 忽略的 `.echo-shadow-stage/s2-chat/`。先启动后端，再从仓库根目录启动静态文件服务器：

```powershell
python -m http.server 5173 --directory .echo-shadow-stage/s2-chat
```

浏览器打开 `http://127.0.0.1:5173`，页面通过现有 HTTP 接口访问对话和本地反思诊断数据。开发环境 CORS 仅允许本机 5173 端口；这套本地实验台不属于产品前端或公共契约。

### Runtime 样例数据

Schema migration 只创建结构，不写入默认业务数据。需要人工检查 Runtime 持久化链路时，在空数据库上运行：

```powershell
uv run --project server python tools/dev/echo_runtime_data.py init --database server/data/echo-runtime.sqlite3
uv run --project server python tools/dev/echo_runtime_data.py export --database server/data/echo-runtime.sqlite3 --output server/data/echo-runtime-export.json
```

初始化工具不会覆盖已有记录；数据库和导出文件位于被 Git 忽略的本地数据目录。

## 运行诊断

普通运行日志输出到标准输出，也可以写入 `server/data/logs/echo.log`。日志只记录关联 ID、状态、错误分类和耗时等白名单字段。SQLite Trace 保存业务生命周期记录，Debug Capture 只在本地显式开启时保存完整模型 I/O；三者职责不同。详细规则见 [可观测基础设施](docs/infrastructure/observability.md)。

需要查看 Prompt、原始响应或结构化解析失败时，将 `settings.toml` 中的 `observability.debug_capture_enabled` 设为 `true`，并按需修改 `debug_capture_path`，然后重启服务。捕获文件可能包含玩家原文和完整上下文，只能保存在本机；调试结束后把该设置改回 `false`。
