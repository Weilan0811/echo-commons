# Echo Commons Server

多名玩家和独立角色实例共同交流的后端基座，版本 0.1.0。SQLite 保存权威状态；后台角色任务调用真实模型，审核后提交消息。已安排的反思任务可以整理摘要、状态、关系和长期记忆；持续自动整理、日记、认识刷新及活动尚未完成。

在本目录运行：

```powershell
uv sync
uv run echo-commons init
uv run echo-commons inspect
```

在 config/model-secrets.toml 填写模型登记引用的实际 credentials，再执行：

```powershell
uv run echo-commons init --example
uv run echo-commons serve
```

默认地址 http://127.0.0.1:8765，`/docs` 提供接口交互说明。init 默认空库；--example 创建两名玩家、两个独立小槿和群聊。只读检查、导出、自定义配置及安装包见 [本地开发](docs/guides/local-development.md)。

从 [完整文档目录](docs/README.md) 阅读。理解设计先看 [系统与运行模型](docs/design/system.md)；前端使用 [HTTP 参考](docs/reference/http-api.md) 和 [接入指南](docs/guides/frontend-integration.md)；当前能力、验证范围和后端待办见 [状态](docs/status.md)。跨前后端的阶段安排见 [项目推进计划](../docs/01-project-roadmap.md)。

消息与轮次读取明确 player_id，私有受众按实际成员区间过滤。实例状态和记忆独立。三种主要反思通过正式内部入口安排后由后台执行，自动封段和扫描新材料调度尚未接入。长期记忆内容仍需要真人材料下的质量验收。
