# Echo Commons Server

后端正在按 [改造方案](../docs/README.md) 重建。实际完成情况见 [实现状态](docs/implementation-status.md)，每个阶段都有独立记录和本地 Git 提交。

## 安装与检查

在 `server/` 目录运行：

```powershell
uv sync
uv run python -m echo_commons.app.cli inspect
uv run pytest tests/infrastructure/test_initial_baseline.py
```

inspect（检查）目前读取正式配置、人物模板和模型登记，显示数据库路径与凭据是否已配置，不显示凭据内容。

## 配置与人物资源

配置相对路径以设置文件所在目录为起点。默认设置为 `config/settings.toml`，真实模型配置为 `config/model-registry.toml`。真实凭据写入被 Git 忽略的 `config/model-secrets.toml`，格式见 `config/model-secrets.example.toml`。

小槿人物模板随包提供；默认加载完整内置资源。需要外部模板时，在 identity 段明确填写 root。指定目录缺失或格式无效会报告错误。

新数据库路径为 `data/echo-commons.sqlite3`。现有实验文件保持原样，当前阶段尚未建立新数据库。

## 当前 HTTP 入口

```powershell
uv run uvicorn echo_commons.app.main:create_app --factory --host 127.0.0.1 --port 8765
```

目前提供 `/health/live` 存活检查。业务接口、数据库生命周期和 Worker（后台执行器）按后续任务接入，完整验收结果会随实际实现更新。

## 设计与实现记录

- [架构与运行模型](../docs/01-backend-architecture.md)
- [目标文件结构](../docs/02-backend-file-structure.md)
- [数据库设计](../docs/05-database-design.md)
- [任务 2 的实际修改与验证](../docs/task-02-implementation.md)
