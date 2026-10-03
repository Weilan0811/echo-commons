# Echo Commons

一个支持真人玩家与多个 AI 角色共同交流、积累记忆并参与活动的平台。

角色拥有独立的身份、状态、关系和记忆。项目从 Echo 后端迁移而来，目前已完成后端基础重构，正在准备建设用户端和管理员端，通过真人测试积累素材，继续完善记忆与长期生活能力。

## 当前能力

- 创建社群、玩家和独立角色实例。
- 支持私聊、群聊、指定受众、提及及消息回复。
- 在后台安排多个角色回应，角色可以选择发言、沉默或查询记忆。
- 按角色可见范围读取消息与记忆，保存状态和关系变化。
- 执行已安排的段反思、连续摘要和长期记忆整理任务。
- 提供任务恢复、运行诊断和数据库导出。

长期记忆整理仍需要真人素材下的质量验证。自动记忆调度、日记、认识刷新、角色主动交流和活动执行尚未完成；前端尚未创建。当前服务用于本地运行，没有玩家账户认证。

## 目录

| 目录 | 内容 |
|---|---|
| `server/` | Python 后端、配置、测试及完整后端文档 |
| `docs/` | 整体推进计划与项目文档入口 |
| `docs/temp_doc/` | 历史设计及重构归档 |

后端使用 FastAPI 提供 HTTP 接口，SQLite 保存业务数据，通过真实模型供应商生成角色回应。

## 本地运行

需要 Python 3.11—3.13 和 uv（Python 项目管理工具）。先安装后端依赖：

```powershell
cd server
uv sync
```

按 [配置说明](server/docs/reference/configuration.md) 配置模型及本地密钥，然后创建示例并启动：

```powershell
uv run echo-commons init --example
uv run echo-commons serve
```

默认服务地址为 `http://127.0.0.1:8765`，打开 `/docs` 查看并操作接口。示例包含两名玩家、两个独立角色和一个群聊。模型密钥、本地数据库及运行捕获文件由 `.gitignore` 排除。

## 文档

- [整体推进计划](docs/01-project-roadmap.md)
- [后端完整文档](server/docs/README.md)
- [当前能力与待办](server/docs/status.md)
- [本地开发与安装](server/docs/guides/local-development.md)
- [接口参考](server/docs/reference/http-api.md)
