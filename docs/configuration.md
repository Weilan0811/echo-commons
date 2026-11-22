# 配置指南

本指南覆盖本地安装、模型服务、人物与记忆、游戏和数据维护。示例使用 PowerShell。后端命令在 `server/` 中执行，前端命令在 `frontend/` 中执行。

## 1. 安装与初始化

需要 Python 3.11—3.13、uv 和 Node.js 22.12+。保留仓库中的同级 `games/` 目录，后端通过本地依赖加载该规则包。

```powershell
cd server
uv sync
if (!(Test-Path -LiteralPath config/model-secrets.toml)) {
    Copy-Item config/model-secrets.example.toml config/model-secrets.toml
}
```

配置模型密钥后执行：

```powershell
uv run echo-commons init --example
uv run echo-commons inspect
uv run echo-commons serve
```

`init --example` 建立示例社群、两名玩家、两个角色实例和群聊。`init` 不带示例参数时建立空库。`inspect` 只读检查数据库与配置。

另开终端，从仓库根目录执行：

```powershell
cd frontend
npm ci
npm run dev
```

默认网页地址为 http://127.0.0.1:5173，后端为 http://127.0.0.1:8765，接口文档位于后端 `/docs`。结束时在两个终端分别按 `Ctrl+C`。

## 2. 三份配置各管什么

| 文件 | 用途 |
| --- | --- |
| `server/config/settings.toml` | 服务地址、存储、后台工作、记忆、游戏分析与图像服务 |
| `server/config/model-registry.toml` | 模型条目、供应商地址、任务路由与本地决策开关 |
| `server/config/model-secrets.toml` | 个人密钥，本地维护，Git 忽略 |

`settings.toml` 中的相对文件路径以设置文件所在目录为基准。模型条目通过 `credential_ref` 读取密钥文件 `[credentials]` 中的同名字段。

### 当前默认模型

| 用途 | 档位或配置 | 所需密钥 |
| --- | --- | --- |
| 日常交流、反思整理 | `profiles.light` → `deepseek_flash` | `deepseek` |
| 可选强化任务 | `profiles.strong` → `qwen_flash`，默认关闭强化路由 | 启用时使用 `dashscope` |
| 人物插画等图像生成 | `[images]`，APIMart `gpt-image-2` | `apimart` |
| 可选本地决策 | `profiles.decision` → `startlux_local` | 本地服务，默认关闭 |

普通聊天的最低密钥配置为：

```toml
[credentials]
deepseek = "填写你的DeepSeekKey"
dashscope = ""
apimart = ""
minimax = ""
```

在已有文件中编辑，保留唯一的 `[credentials]` 段。更换模型时，同时核对模型名、地址、协议、凭据引用与供应商参数。实际配置以仓库登记文件为准。

`routing.strong_enabled` 默认关闭，人物采访等强化任务此时沿用主力模型，一个主力凭据即可覆盖文本功能。显式启用强化路由后，补齐相应模型密钥。请求失败按任务重试规则处理，不会自动改变路由策略。主力条目可选择 DeepSeek、DashScope 或 MiniMax，按各自条目的 `credential_ref` 填写密钥。

## 3. 前端连接与社群运行

前端默认访问后端 8765 端口。地址变化时，在 `frontend/.env.local` 设置并重启前端：

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8765
```

后端的跨域来源需要包含实际网页地址。默认已配置：

```toml
[server]
cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
```

修改已有段落，避免重复添加同名段。前端改用其他端口时同步修改来源并重启后端。

角色自动回应同时需要：有效模型配置、`[workers].enabled = true`、运行中的社群，以及准备就绪并加入会话的角色。暂停社群后仍可查看已有内容，角色停止回应。

## 4. 人物创建与记忆模式

网页“角色”页面支持从模板创建实例，也支持编写自定义人物：基础人设、过去故事、人物采访、审核与确认。未完成的内容保存在人物草稿中；确认后可入住所在社群。

| 记忆模式 | 行为与成本 |
| --- | --- |
| 简单模式 | 检索作者原文与相关材料，使用段摘要和连续摘要；有关系材料时需要准备初始关系 |
| 完整模式 | 在上述能力之外，将可知材料与经历整理为长期事实、认知和相关视图；准备时间与模型调用更多 |

模式在实例创建后不可切换。“记忆准备中”表示初始化尚未完成，此时角色不能加入会话。作者设置为角色不知情的材料不会作为角色已知事实使用。

对话和后台摘要、长期整理都可能调用模型。角色越多、材料越长、持续交流越久，后台用量通常越多。`[workers]` 设置并发与类别份额；`[reflection]` 设置单次整理预算。

## 5. 游戏与可选模型

### 五子棋分析

在 `server/` 执行：

```powershell
uv run python tools/install_rapfi.py
```

工具下载固定发布版 Rapfi 及配套资源。默认位置与预算由已有设置段控制：

```toml
[game_analysis.rapfi]
directory = "../data/game-analysis/rapfi/250615"
threads = 1
hash_memory_mb = 64
search_time_ms = 500
candidates = 6
timeout_seconds = 10
```

引擎在首次分析时启动，服务退出时回收。普通聊天与真人对局可以独立运行。

### 飞行棋与局内聊天

飞行棋使用内置规则分析，无需外部引擎。五子棋和飞行棋角色自动行动需要普通模型、后台工作及运行中的社群。Kingdomino 当前支持真人对局与局内聊天。

`[activity_reactions]` 调整局内主动交流的间隔、概率和频率，不影响必须处理的游戏动作。失败的自动任务需要根据错误和任务状态恢复；重复发送聊天消息不等于重新执行动作。

### 本地决策服务

默认群聊使用 `[participation].mode = "remote_rules"`，按规则选人，回应任务同时决定是否表达。可选 `remote_willingness` 或 `local_willingness`：分别由远端模型或本地模型先对候选意愿评分，再安排表达，会增加逐角色判断开销。两种意愿模式共用持久批次、阈值和选人策略。

默认 `[decision].enabled = false`。使用本地意愿模式或本地活动决策前，按仓库 [本地决策说明](../server/docs/design/decision-models.md) 配置兼容本地服务，并核对条目的模型、地址和协议。当前条目使用 `startlux_decision` 协议，不能仅替换成任意聊天接口地址。

这项能力与 Rapfi 分开：Rapfi 分析五子棋局势，本地决策服务处理其适用的角色决策。

## 6. 保存、导出与恢复

默认数据库为 `server/data/echo-commons.sqlite3`，图像位于 `server/data/assets/images/`，日志位于 `server/data/logs/`。这些路径由配置决定。

在 `server/` 中导出一致的数据库副本：

```powershell
uv run echo-commons export --output data/exports/community.sqlite3
```

目标已存在时命令拒绝覆盖。数据库包含对话和私人记忆；需要完整备份时，还应保存关联图片、自定义人物相关资源与使用中的配置。密钥分别保管。

自定义配置通过全局参数选择：

```powershell
uv run echo-commons --settings config/settings.toml inspect
```

`--settings` 放在子命令前。服务重启后，持久任务按租约和业务状态恢复；已完成的动作不会因为表达重试而再次执行。最终失败和业务取消需要分别检查，恢复过程不保证所有内容错误都能自动解决。

## 7. 常见问题

| 现象 | 检查方法 |
| --- | --- |
| 看得到网页，角色不回应 | 检查身份、社群状态、角色成员资格、准备状态、后台工作和模型密钥 |
| 前端请求失败 | 核对 `VITE_API_BASE_URL`、后端端口与完整跨域来源 |
| 人物采访失败 | 检查主力配置；显式启用强化档时再检查其密钥 |
| 五子棋角色不行动 | 检查 Rapfi 安装、实际轮次、角色准备状态及活动任务错误 |
| 角色一直准备中 | 查看初始化任务状态与错误、模型额度和后台是否运行 |
| `expression_not_arranged` | 查看活动表达与关联任务；保留对局和任务信息以便诊断，勿将其视为动作成功 |

完整字段参考位于仓库 [配置字段参考](../server/docs/reference/configuration.md)；任务与数据结构阅读路径见[架构与开发指南](architecture.md)。
