# Echo Commons Server

多名玩家和独立角色实例共同交流的后端基座，版本 0.1.0。SQLite 保存权威状态；后台角色任务调用真实模型，审核后提交消息或游戏动作。自动记忆链按材料量和等待时间安排段摘要、连续性压缩、长期整理与认识刷新；日记、局内接话和游戏经历整理尚未完成。

首次使用请按照根目录的[本地运行说明](../README.md#本地运行)安装依赖、创建密钥文件、配置模型及启动前端。已经配置好的后端，在本目录运行：

```powershell
uv sync
uv run echo-commons init --example
uv run echo-commons inspect
uv run echo-commons serve
```

默认地址 http://127.0.0.1:8765，`/docs` 提供接口交互说明。init 默认空库；--example 创建两名玩家、两个独立小槿和群聊。只读检查、导出、自定义配置及安装包见 [本地开发](docs/guides/local-development.md)。

从 [完整文档目录](docs/README.md) 阅读。理解设计先看 [系统与运行模型](docs/design/system.md)；前端使用 [HTTP 参考](docs/reference/http-api.md) 和 [接入指南](docs/guides/frontend-integration.md)；当前能力、验证范围和后端待办见 [状态](docs/status.md)。跨前后端的阶段安排见 [项目推进计划](../docs/01-project-roadmap.md)。

五子棋玩法分析使用固定版本 Rapfi。在本目录执行 `uv run python tools/install_rapfi.py` 安装程序与配套权重，应用在首次分析时启动并在关闭时回收。玩法分析、扩展接口和资源配置见[玩法分析设计](docs/design/game-analysis.md)。已就绪的角色受到邀请并开始对局后，后台在真实行动机会到来时自动处理。

消息与轮次读取明确 player_id，私有受众按实际成员区间过滤。实例状态和记忆独立。四种反思支持后台自动安排和正式管理入口；简单模式整理摘要，完整模式进一步维护状态、关系、长期页和认识。长期记忆内容仍需要真人材料下的质量验收。

普通聊天按模型容量组织当前历史、临近场景和相关记忆；各会话独立归段，容量不足时等待摘要完成。`[memory.context]` 配置历史分配比例，模型条目的 `context_window_tokens` 和 `token_counter` 配置容量与计量方式，详见[配置参考](docs/reference/configuration.md#3-模型登记)。游戏经历的正式来源及整局摘要由后续 Activity 接入阶段实现。

Activity 已提供行动、局内回应、事件与安静期间交流，以及正式消息发布和独立表达恢复。`[activity]` 控制输入及人物材料预算，`[activity_reactions]` 控制主动机会的概率与间隔；普通行动使用 `activity_turn`，按需正文使用 `activity_expression`，沿用现有密钥配置。开启 `[decision]` 后由本地模型选择候选或进一步理解；游戏只有一个合法动作时无需调用行动模型。范围与使用方式见[活动输入](docs/design/activity-context.md)、[角色行动](docs/design/activity-actions.md)和[局内表达](docs/design/activity-expression.md)。
