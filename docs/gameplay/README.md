# 小游戏开发文档

更新日期：2026-11-22。五子棋与飞行棋已接入真人和角色参与、局内交流及经历整理；Kingdomino 当前支持真人对局与局内聊天。实际能力、验证范围和限制见[后端状态](../../server/docs/status.md)及[前端状态](../../frontend/docs/status.md)。

| 文档 | 阅读用途 |
|---|---|
| [产品策划](策划.md) | 游戏体验、玩法目标与共同经历 |
| [05 号共同阶段实施计划](../archive/implementation/05-gameplay-foundation-implementation-plan.md) | 当前代码依据、六个实施单元、具体开发与验收要求 |
| [并行开发计划](../archive/gameplay/并行开发计划.md) | 规则来源、开发阶段、分工和联合验收 |
| [飞行棋基础规则](飞行棋基础规则.md) | 飞行棋基础阶段的唯一规则文本：来源、棋盘几何、动作与项目决定 |
| [Kingdomino 基础规则](Kingdomino基础规则.md) | Kingdomino 基础阶段的唯一规则文本：来源、连接与计分、动作与项目决定 |
| [共同基础与文件结构](共同基础与文件结构.md) | 建立真实可玩基础、文件职责、依赖与启动 |
| [共同基础交接](../archive/gameplay/共同基础交接.md) | 共同基础阶段的历史交接；当前行动、表达与经历能力见角色活动设计 |
| [游戏与角色活动接口契约](游戏与角色活动接口.md) | 游戏种类、大厅、对局生命周期、内部职责、角色加入与进行中操作 |
| [角色活动设计](../../server/docs/design/activity-integration.md) | 局内会话、决策、调用策略、恢复和经历来源 |
| [06 号角色活动实施计划](../archive/implementation/06-activity-implementation-plan.md) | 主动对话、决策模型、智能接话及 Activity 分单元实现与验收 |
| [决策模型游戏案例调研](../archive/gameplay/决策模型游戏案例调研.md) | 公开代码、模型局限及对项目的实际启示 |
| [代码设计入口](代码.md) | 运行结构与设计阅读顺序 |
| [素材需求](../archive/gameplay/美术.md) | 两款后续游戏的素材规格与整理依据 |

五子棋、飞行棋和 Kingdomino 共用游戏基础设施，角色活动通过宿主后端接入。实际已交付能力见[后端状态](../../server/docs/status.md)和[前端状态](../../frontend/docs/status.md)。
