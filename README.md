# Echo Commons

一个支持真人玩家与多个 AI 角色共同交流、积累记忆并参与活动的平台。

角色拥有独立的身份、状态、关系和记忆。项目包含 Python 后端、网页用户端和管理端，以及独立的桌游规则包。

## 当前能力

- 创建社群、玩家和独立角色实例。
- 支持私聊、群聊、指定受众、提及及消息回复。
- 在后台安排多个角色回应，角色可以选择发言、沉默或查询记忆。
- 按角色可见范围读取消息与记忆，保存状态和关系变化。
- 自动安排段摘要、连续压缩、长期记忆整理和认识刷新，支持简单与完整记忆模式。
- 通过内部主动对话入口生成角色开场，普通群聊可选用本地决策模型判断参与。
- 通过网页进行五子棋、飞行棋和 Kingdomino（多米诺王国）的真人对局与局内聊天。
- 使用 Rapfi（五子棋分析引擎）提供真实候选与局势分析。
- 提供任务恢复、运行诊断和数据库导出。

角色已经能够参与正式五子棋和飞行棋对局并自动行动，支持普通角色模型和本地决策模型两种配置，任务可暂停与重启恢复。局内回应、行动配套发言、事件反应及安静期间交流已接通正式消息，表达失败可以独立恢复。游戏经历按参赛区间整理，胜负产生后保留赛后交流，结束活动后整理整局摘要。日记暂缓，记忆内容质量继续通过真实互动验证。当前服务用于本地运行，没有玩家账户认证。详细进度见[后端状态](server/docs/status.md)和[前端状态](frontend/docs/status.md)。

## 目录

| 目录 | 内容 |
|---|---|
| `server/` | Python 后端、配置、测试及完整后端文档 |
| `frontend/` | 网页用户端、管理端和游戏页面 |
| `games/` | 独立游戏规则、持久化和公开接口 |
| `docs/` | 整体推进计划与项目文档入口 |

后端使用 FastAPI 提供 HTTP 接口，SQLite 保存业务数据，通过真实模型供应商生成角色回应。

## 本地运行

需要 Python 3.11—3.13、uv（Python 项目管理工具），以及 Node.js 22.12.0 或以上版本和 npm（前端包管理工具）。下面使用 PowerShell，起始位置为仓库根目录。

### 1. 安装后端依赖

```powershell
cd server
uv sync
```

保留同级的 `games/` 目录；`uv sync` 会同时加载本工作目录中的游戏包。后续后端命令继续在 `server/` 中执行。

### 2. 配置模型与密钥

| 文件 | 用途 |
|---|---|
| [settings.toml](server/config/settings.toml) | 服务地址、跨域来源、数据目录、Rapfi 和生图配置 |
| [model-registry.toml](server/config/model-registry.toml) | 模型、供应商地址、任务路由及本地决策开关 |
| `server/config/model-secrets.toml` | 个人 API（接口）密钥，由本地维护，Git 忽略此文件 |

首次运行时，从[密钥格式示例](server/config/model-secrets.example.toml)创建自己的密钥文件。下面的命令保留已有文件：

```powershell
if (!(Test-Path -LiteralPath config/model-secrets.toml)) {
    Copy-Item -LiteralPath config/model-secrets.example.toml -Destination config/model-secrets.toml
}
```

打开 `config/model-secrets.toml`，在 `[credentials]` 中填写实际密钥。按仓库当前默认配置：

| 功能 | 密钥字段 | 对应配置 |
|---|---|---|
| 日常对话与记忆整理 | `deepseek` | `model-registry.toml` 中的 `profiles.light`（轻量档） |
| 人物采访检查等强化任务 | `dashscope` | `profiles.strong`（强化档），通过阿里云模型服务调用 |
| 角色插画等图像生成 | `apimart` | `settings.toml` 中的 `images.credential_ref` |

模型条目的 `credential_ref` 指定读取哪个密钥字段。例如 `credential_ref = "deepseek"` 对应 `[credentials]` 中的 `deepseek`。更换模型时，检查相应条目的模型名、地址、密钥引用和供应商参数；完整格式见[配置参考](server/docs/reference/configuration.md)。未使用功能的密钥可以保持空值，调用该功能时需要补齐。

`model-registry.toml` 中的 `[decision].enabled` 默认关闭，普通对话无需启动本地决策服务。需要启用时，按[本地决策模型说明](server/docs/design/decision-models.md)启动服务并核对地址；它与 Rapfi 分别配置。

### 3. 安装 Rapfi

飞行棋使用内置固定规则评分，无需安装额外分析程序或训练模型。算法与评价范围见[玩法分析设计](server/docs/design/game-analysis.md#7-飞行棋规则分析)。

使用五子棋分析功能时执行：

```powershell
uv run python tools/install_rapfi.py
```

工具安装固定发布版的程序、配置和配套权重，无需模型 API 密钥。当前安装目录和计算预算位于 `config/settings.toml` 的 `[game_analysis.rapfi]`：

```toml
[game_analysis.rapfi]
directory = "../data/game-analysis/rapfi/250615"
threads = 1
hash_memory_mb = 64
search_time_ms = 500
candidates = 6
timeout_seconds = 10
```

直接编辑已有配置段。`directory` 相对于设置文件所在目录解析，上述配置对应 `server/data/game-analysis/rapfi/250615/`。应用在首次分析时启动引擎，退出时回收。普通聊天和真人对局可以单独运行。

角色自动下棋还需要有效的普通模型凭据、开启后台工作，以及处于运行状态的社群。邀请就绪的角色加入对局并开始后，后台在轮到它时自动处理。开启本地决策配置时，本地服务需要保持运行。局内回应及主动反应通过现有聊天界面显示，也允许角色保持安静。`settings.toml` 的 `[activity_reactions]` 配置主动机会的概率、间隔和频率；它不影响玩家正式回应与必须执行的游戏动作。具体规则见[角色行动](server/docs/design/activity-actions.md)、[局内协调](server/docs/design/activity-coordination.md)与[局内表达](server/docs/design/activity-expression.md)。

其他安装目录、已下载发布包及程序选择见[玩法分析与安装说明](server/docs/design/game-analysis.md)。

### 4. 初始化并启动后端

```powershell
uv run echo-commons init --example
uv run echo-commons inspect
uv run echo-commons serve
```

示例包含两名玩家、两个独立角色和一个群聊。希望创建空数据库时，使用 `uv run echo-commons init`。`inspect` 用于检查数据库与配置状态；真实模型调用仍需对应的有效密钥。

默认后端地址为 [http://127.0.0.1:8765](http://127.0.0.1:8765)，[接口操作页面](http://127.0.0.1:8765/docs)可查看和调用接口。保持这个终端运行。

### 5. 启动前端

另开一个终端，从仓库根目录执行：

```powershell
cd frontend
npm ci
npm run dev
```

默认打开 [http://127.0.0.1:5173](http://127.0.0.1:5173)。前端直接连接后端，后端 `config/settings.toml` 的 `[server].cors_origins` 需要包含浏览器页面的完整来源，例如：

```toml
[server]
cors_origins = ["http://localhost:5173", "http://127.0.0.1:5173"]
```

仓库当前的开发配置已包含这两个来源。修改已有 `[server]` 段并重启后端；如果前端使用其他端口，也要填写对应来源。

前端默认连接 `http://127.0.0.1:8765`。后端地址变化时，在 `frontend/.env.local` 中设置以下变量并重启前端，格式见 [.env.example](frontend/.env.example)：

```dotenv
VITE_API_BASE_URL=http://127.0.0.1:8765
```

结束运行时，在前后端终端分别按 `Ctrl+C` 正常退出。密钥、前端本地环境文件、数据库和引擎运行资源由 `.gitignore` 排除。更多初始化、导出及安装包用法见[本地开发与安装](server/docs/guides/local-development.md)。

## 文档

- [整体推进计划](docs/01-project-roadmap.md)
- [后端完整文档](server/docs/README.md)
- [前端说明](frontend/README.md)
- [独立游戏包](games/README.md)
- [当前能力与待办](server/docs/status.md)
- [本地开发与安装](server/docs/guides/local-development.md)
- [接口参考](server/docs/reference/http-api.md)
- [模型、密钥与运行配置](server/docs/reference/configuration.md)
- [Rapfi 与玩法分析](server/docs/design/game-analysis.md)
- [Activity 实施记录（06，已封档）](docs/06-activity-implementation-plan.md)
- [Activity 上下文与执行修正计划（07）](docs/07-activity-context-and-execution-correction-plan.md)
