# Echo Commons

一个支持真人玩家与多个 AI 角色共同交流、积累记忆并参与活动的平台。

角色拥有独立的身份、状态、关系和记忆。项目包含 Python 后端、网页用户端和管理端，以及独立的桌游规则包。

## 当前能力

- 创建社群、玩家和独立角色实例。
- 支持私聊、群聊、指定受众、提及及消息回复。
- 在后台安排多个角色回应，角色可以选择发言、沉默或查询记忆。
- 按角色可见范围读取消息与记忆，保存状态和关系变化。
- 自动安排段摘要、连续压缩、长期记忆整理和认识刷新，支持简单与完整记忆模式。
- 通过主动对话入口生成角色开场，群聊支持规则、远端意愿和本地意愿三种接话模式。
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

### 2. 配置一个主力模型

模型登记在[model-registry.toml](server/config/model-registry.toml)，密钥单独保存在Git忽略的`server/config/model-secrets.toml`。首次运行，复制密钥示例，保留已有文件：

```powershell
if (!(Test-Path -LiteralPath config/model-secrets.toml)) {
    Copy-Item -LiteralPath config/model-secrets.example.toml -Destination config/model-secrets.toml
}
```

从下面选择一家，在`model-registry.toml`现有的`[profiles]`中修改`light`，并在密钥文件的`[credentials]`填写对应字段。三个条目已经提供完整配置，普通聊天、角色创作和记忆整理只需要所选这一份密钥。

| 供应商 | `profiles.light` | 密钥字段 | 推荐文本型号 |
|---|---|---|---|
| DeepSeek | `"deepseek_flash"` | `deepseek` | `deepseek-flash` |
| DashScope（阿里云百炼） | `"qwen_flash"` | `dashscope` | `qwen3.8-flash` |
| MiniMax | `"minimax_flash"` | `minimax` | `MiniMax-M3.1-Flash` |

例如默认DeepSeek配置需要填写：

```toml
# config/model-secrets.toml
[credentials]
deepseek = "在本地填写你的密钥"
```

可直接使用仓库中的登记文件；下列折叠示例也可各自作为一份完整的`model-registry.toml`。请从供应商控制台确认模型名称和地区，地址与密钥属于同一地区。MiniMax示例保持思考开启，默认采用低思考深度。

<details>
<summary>DeepSeek单模型完整示例</summary>

```toml
schema_version = 1
[runtime]
backend = "openai_compatible"
active_profile = "light"
[gateway]
request_timeout_seconds = 120
max_output_tokens = 20480
[profiles]
light = "primary"
[routing]
strong_enabled = false
[entries.primary]
model_vendor = "deepseek"
model = "deepseek-flash"
base_url = "https://api.deepseek.com"
credential_ref = "deepseek"
access_route = "deepseek-direct"
extra_body = { thinking = { type = "disabled" } }
```

</details>

<details>
<summary>DashScope单模型完整示例</summary>

```toml
schema_version = 1
[runtime]
backend = "openai_compatible"
active_profile = "light"
[gateway]
request_timeout_seconds = 120
max_output_tokens = 20480
[profiles]
light = "primary"
[routing]
strong_enabled = false
[entries.primary]
model_vendor = "dashscope"
model = "qwen3.8-flash"
base_url = "https://dashscope.aliyuncs.com/compatible-mode/v1"
credential_ref = "dashscope"
access_route = "dashscope-direct"
extra_body = { enable_thinking = false }
```

</details>

<details>
<summary>MiniMax单模型完整示例</summary>

```toml
schema_version = 1
[runtime]
backend = "openai_compatible"
active_profile = "light"
[gateway]
request_timeout_seconds = 120
max_output_tokens = 20480
[profiles]
light = "primary"
[routing]
strong_enabled = false
[entries.primary]
model_vendor = "minimax"
model = "MiniMax-M3.1-Flash"
base_url = "https://api.minimax.cn/v1"
credential_ref = "minimax"
access_route = "minimax-direct"
extra_body = { reasoning_split = true, reasoning_effort = "low" }
```

</details>

增强模型默认关闭。需要双模型时，在现有`[profiles]`填写`strong`对应的条目，并将`[routing].strong_enabled`改为`true`，填写增强条目引用的密钥。关闭时，采访检查等增强任务也使用主力。失败重试继续调用原模型。

模型名称可以自行修改，前提是它支持所选供应商的接口。配置和路径完整说明见[配置参考](server/docs/reference/configuration.md)。取得密钥与地区地址可查阅[DeepSeek文档](https://api-docs.deepseek.com/)、[百炼文档](https://help.aliyun.com/zh/model-studio/)和[MiniMax文档](https://platform.minimax.cn/docs/api-reference/text-openai-api)。

#### 可选：生成图片

生图独立配置；未填写生图密钥仍可聊天和上传图片。选择以下一份替换`config/settings.toml`现有的`[images]`段，在密钥文件填写对应`credential_ref`。同步生成可能需要等待几十秒。

<details>
<summary>三家生图配置</summary>

```toml
# DashScope：Qwen Image 3.0普通版，使用原生图像接口
[images]
provider = "dashscope"
model = "qwen-image-3.0"
base_url = "https://dashscope.aliyuncs.com/api/v1"
credential_ref = "dashscope"
request_timeout_seconds = 120
```

```toml
# MiniMax：原生同步图像接口
[images]
provider = "minimax"
model = "MiniMax-H3-Image"
base_url = "https://api.minimax.cn/v1"
credential_ref = "minimax"
request_timeout_seconds = 120
```

```toml
# APIMart：异步提交与任务查询
[images]
provider = "apimart"
model = "gpt-image-2"
base_url = "https://api.apimart.ai/v1"
credential_ref = "apimart"
request_timeout_seconds = 120
```

DashScope适配Qwen Image 3.0与2.1的原生图像家族，MiniMax适配H3文生图家族，APIMart沿用其异步图像协议。可以填写适配范围内的其他型号。原生MiniMax图像编辑使用另一接口，当前入口用于文生图。已提交任务保存原供应商配置，修改默认值后继续处理原任务。

</details>

#### 可选：选择群聊接话方式

在`config/settings.toml`现有的`[participation]`段选择模式：

| `mode` | 行为与调用开销 |
|---|---|
| `"remote_rules"`，默认 | 按规则依次安排候选，由普通回应任务判断并表达；工具往返或修正可能增加请求 |
| `"remote_willingness"` | 每位合格候选分别远端评分，选中后再生成正文，开销随候选人数增加 |
| `"local_willingness"` | 每位候选使用本地服务评分，正文仍调用远端主力 |

```toml
[participation]
mode = "remote_rules"
temperature = 0.1
```

意愿模式主要依据模型分数选人，长期参与修正最多影响10%的权重。远端评分默认使用主力，`remote_entry_id`可以指定其他已登记条目。推荐阈值已经随包提供：DeepSeek Flash与Qwen3.8-Flash为0.85，MiniMax-M3.1-Flash低思考深度为0.86；其他远端型号默认约0.8533。它们来自固定小样本的配置测量，正文表现仍受实际角色材料影响。高级配置`threshold`可覆盖阈值，服务不会自动调用模型校准。

本地意愿模式需要先启动兼容的StartLux服务，在`model-registry.toml`的`[profiles]`保留`decision`条目，并将本地条目的`model`填写为服务实际返回的名称，`base_url`填写服务地址。未知本地二分类模型默认阈值0.5；只有使用同一训练权重时才采用对应推荐值。权重和训练数据不随本项目分发。启动方法与本地协议见[本地决策模型](server/docs/design/decision-models.md)。

随包本地条目使用0.8B原始模型名称、8192 token容量及对应分词器。首次启用本地模式时下载并缓存分词文件，普通远端模式无需下载。更换本地权重时，模型名称、容量与分词器应与服务一致。

Windows使用Transformers部署0.8B时，可以在安装StartLux及PyTorch的独立环境运行`server/tools/serve_local_decision.py`。它保留官方自检，支持本机缺少融合注意力内核的情况；具体安装、输入长度与启动参数见上述说明。

`[decision].enabled`控制Activity的本地行动判断，独立于群聊模式和增强开关。普通聊天无需启动本地模型。配置文件修改后重启后端，进行中的任务继续使用保存的配置。

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
