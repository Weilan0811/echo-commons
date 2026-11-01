# 本地决策模型

## 职责与调用入口

`DecisionGateway` 连接 StartLux 的 `/v1/systemone` 接口。Social（社交调度模块）和 Activity（角色活动模块）负责组织角色材料、可见情景、问题与候选，并解释选择结果。客户端负责协议校验、连接、并发等待、期限、有限重试、用量和诊断记录。

应用通过 `application.decisions` 提供客户端。配置关闭时该值为空，应用不会创建决策 HTTP 客户端或发送探测请求。现有文本生成继续使用 `OpenAICompatibleGateway`。决策客户端不生成角色正文，也不创建聊天、游戏或数据库任务。

调用方构造 `DecisionRequest`，提供 `invocation_id`、`trace_id`、`agent_id`、`state` 和 `questions`，然后调用 `await application.decisions.decide(request)`。问题名称、选项身份和选项说明由调用方提供。

| 类型 | 输入 | 返回 |
|---|---|---|
| `ChoiceQuestion` | 选择说明、选项身份到说明的字典 | 选项身份、原始置信度及各选项概率，可选的无匹配概率 |
| `NoulQuestion` | 是否判断的说明 | 肯定答案的概率 |
| `ScoreQuestion` | 判断说明、从低到高的 2 至 10 个等级 | 按等级位置计算的评分、等级说明、置信度及概率 |

客户端检查问题与回答的名称、类型及选项对应关系。概率保持供应商定义；`confidence`（置信度）与 `none_probability`（无匹配信号）分别保留。业务需要“进一步理解”时，应提供相应候选。多个问题独立判断，有依赖的后续问题由业务分步提交。

## 配置

使用 `server/config/model-registry.toml`，安装包提供同样的配置模板。决策能力默认关闭，已有文本模型登记和凭据文件保留。启用时设置：

```toml
[profiles]
decision = "startlux_local"

[decision]
enabled = true
profile = "decision"
timeout_seconds = 30
input_max_chars = 32000

[decision.controls]
think_mode = "never"

[entries.startlux_local]
protocol = "startlux_decision"
model_vendor = "startlux"
model = "4B-AutoThink-GGUF"
base_url = "http://127.0.0.1:8090"
access_route = "local-startlux-llamacpp"
request_timeout_seconds = 30
max_retries = 1
```

将这些字段合并到已有同名配置表。`base_url` 是服务根地址，客户端追加 `/v1/systemone`。`model` 必须与服务实际返回的名称一致；StartLux 的模型由部署服务加载，请求字段不能切换权重。

无需认证的决策服务省略 `credential_ref`。需要认证时，填写凭据引用，并将实际密钥放入忽略提交的 `model-secrets.toml`。本地客户端直接连接配置地址，不使用环境代理。

`input_max_chars` 限制实际 JSON 请求的字符数，包括问题和选项。它与模型服务的 token（文本计量单位）上限分别检查。`timeout_seconds` 包含并发等待、HTTP 调用和重试等待；条目的 `request_timeout_seconds` 限制单次 HTTP 请求。请求还可提供更早的 `deadline_utc`。

高频路径默认 `think_mode="never"`。可显式使用 `auto` 或 `always`，并配置 `gate`、`think_budget`、`mix`、`thought_generation`、`allow_none`、`none_check`、`return_details` 和 `return_thought`。请求提供的 `DecisionControls` 是完整的一组控制参数。

## 执行、恢复与关闭

`prepare(request)` 返回可序列化的已准备请求，固定模型条目、实际地址、模型名称、凭据引用、输入上限、超时、重试次数和推理参数；它不发送请求、不保存数据库。持久任务的调用方应保存这份请求，再在恢复时读取。凭据值不进入请求快照，继续从凭据文件读取。Social 与 Activity 的持久判断任务由各自实现单元接入。

模型调用在写事务外执行，通过现有 `ModelBudget.slot()` 共享并发额度。调用方可传入 `before_request`，在每次实际尝试前复核任务资格。取消继续向上传播，并释放并发额度；等待超过期限返回 `timeout`。应用关闭时释放 HTTP 连接，外部模型服务继续由部署者管理。

HTTP 和连接错误转换成已有 `ModelGatewayError`：连接失败、429 和临时服务错误允许有限重试；认证、请求及响应协议错误直接返回失败。关闭决策能力与服务故障分别处理，业务决定后续任务如何执行。

调用记录包含实际模型、条目、尝试次数、耗时和原服务用量。`DecisionResponse.usage` 保留服务未提供计量的空值；共同 `UsageSummary` 用于现有累计计数。一次外部 HTTP 请求可能包含多个问题及服务内部推理步骤，不能把 HTTP 请求数当成底层前向计算次数。

开启已有本地调试捕获后，实际请求、原响应和校验结果进入共同捕获目录，并提供易读的请求文本；普通日志不包含情景正文或凭据。

## 真实验证

验证入口为 `tests/infrastructure/test_decision_models.py`。真实模型测试沿用 `model` 标记；普通测试验证配置、输入校验、冻结请求、真实连接失败、有限重试和并发等待取消。运行真实服务验证：

```powershell
uv run pytest tests/infrastructure/test_decision_models.py -m "model or not model"
```

2026-10-20 的部署报告为 `4B-AutoThink-GGUF`，使用 llama.cpp，服务地址 `http://127.0.0.1:8090`，上下文长度 65536，文本输入，服务默认采用 `auto`；后端默认显式发送 `never`。这些信息来自实际 `/health`，设备型号和权重文件版本需要由部署环境提供。

普通群聊通过 social 的参与判断阶段接入该客户端，保存固定请求和正式选择，复用同一次角色机会的上下文与任务，见[智能参与判断](conversation-and-social.md#41-智能参与判断)。[游戏行动](activity-actions.md)使用候选选择与意图问题；[局内回应](activity-coordination.md)复用参与意愿问题，在 Activity 内保存独立阶段结果。进一步理解进入普通角色模型，共用原输入与模型额度。
