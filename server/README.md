# Echo Commons Server

多名玩家和独立角色实例共同交流的后端基座，版本 0.1.0。SQLite 保存权威状态；后台角色任务调用真实模型，审核后提交消息。自动记忆链按材料量和等待时间安排段摘要、连续性压缩、长期整理与认识刷新；日记和活动尚未完成。

首次使用请按照根目录的[本地运行说明](../README.md#本地运行)安装依赖、创建密钥文件、配置模型及启动前端。已经配置好的后端，在本目录运行：

```powershell
uv sync
uv run echo-commons init --example
uv run echo-commons inspect
uv run echo-commons serve
```

默认地址 http://127.0.0.1:8765，`/docs` 提供接口交互说明。init 默认空库；--example 创建两名玩家、两个独立小槿和群聊。只读检查、导出、自定义配置及安装包见 [本地开发](docs/guides/local-development.md)。

从 [完整文档目录](docs/README.md) 阅读。理解设计先看 [系统与运行模型](docs/design/system.md)；前端使用 [HTTP 参考](docs/reference/http-api.md) 和 [接入指南](docs/guides/frontend-integration.md)；当前能力、验证范围和后端待办见 [状态](docs/status.md)。跨前后端的阶段安排见 [项目推进计划](../docs/01-project-roadmap.md)。

五子棋玩法分析使用固定版本 Rapfi。在本目录执行 `uv run python tools/install_rapfi.py` 安装程序与配套权重，应用在首次分析时启动并在关闭时回收。玩法分析、扩展接口和资源配置见[玩法分析设计](docs/design/game-analysis.md)。角色自动行动继续由后续 Activity 单元接入。

消息与轮次读取明确 player_id，私有受众按实际成员区间过滤。实例状态和记忆独立。四种反思支持后台自动安排和正式管理入口；简单模式整理摘要，完整模式进一步维护状态、关系、长期页和认识。长期记忆内容仍需要真人材料下的质量验收。

Activity 已提供行动、局内回应和事件反应的输入准备，保存原观察、人物材料和局内工作记忆，支持重试与重启恢复。`[activity]` 控制输入及人物材料预算，沿用现有模型与密钥配置；范围、内部入口和后续生命周期接入见[活动输入设计](docs/design/activity-context.md)。
