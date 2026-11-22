# 本地决策模型

## 职责与调用入口

`DecisionGateway` 连接 StartLux 的 `/v1/systemone` 接口。Social（社交调度模块）和 Activity（角色活动模块）负责组织角色材料、可见情景、问题与候选，并解释选择结果。客户端负责协议校验、连接、并发等待、期限、有限重试、用量和诊断记录。

应用通过`application.decisions`提供客户端。Activity本地判断由`[decision].enabled`控制，群聊由`participation.mode="local_willingness"`控制。两者分别开启，按实际消费者复用客户端；都关闭且没有待恢复的本地任务时，不创建本地客户端或发送探测请求。正文使用`OpenAICompatibleGateway`，决策客户端只负责判断协议。

Activity 的交流判断在已有角色与局势、聊天和新增来源之后，额外提供 `交流判断依据`，明确待回应消息、近期本人发言、交流安排、新事件和当前意图。判断交流价值时参考已完成与待发表内容，普通操作不自动构成新的开口理由。行动问题与交流问题继续使用同一次请求，交流问题不依赖尚未返回的动作答案；实际动作由后续正文阶段使用。只接话的任务明确其没有行动权限。

这项组织用于Activity。普通群聊的本地意愿模式使用`speak`与`silent`两个选项，关闭内部无匹配候选检查，读取`speak`概率，再交给与远端共用的阈值及抽样策略。意图逐项去留、新意图理解、候选和转交规则沿用Activity契约；真实行为与选项概率分别记录。

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
model = "StartLux-Decision-v1.1-0.8B-Instant"
base_url = "http://127.0.0.1:8090"
access_route = "local-startlux"
request_timeout_seconds = 30
max_retries = 1
max_output_tokens = 64
context_window_tokens = 8192
token_counter = "hf:startlux-models/StartLux-Decision-v1.1-0.8B-Instant"
```

将这些字段合并到已有同名配置表。`base_url` 是服务根地址，客户端追加 `/v1/systemone`。`model` 必须与服务实际返回的名称一致；StartLux 的模型由部署服务加载，请求字段不能切换权重。

本地输入使用该权重的真实分词器，避免UTF-8字节上界提前拒绝可用的中文材料。首次启用时，后端通过Tokenizers下载并缓存指定模型的分词文件，无需加载权重或安装PyTorch。更换模型时同时核对`token_counter`。离线缓存设置见[配置参考](../reference/configuration.md)。输入预算统计完整请求材料，最终服务按其实际模板检查容量。

## Windows的Transformers启动入口

在独立的模型环境中安装StartLux及其Transformers依赖，后端应用本身无需安装PyTorch。从已经下载的StartLux源码安装时执行：

将下面三处路径改成真实路径，在`server/`目录执行：

```powershell
$modelPython = "模型环境的python.exe完整路径"
$startluxSource = "StartLux源码目录"
$modelDirectory = "模型目录"
uv pip install --python $modelPython -e "${startluxSource}[transformers]"
& $modelPython tools/serve_local_decision.py --model $modelDirectory --port 8090
```

上面的工具路径相对于`server/`。默认上报模型目录名称，可用`--name`指定稳定名称，并让模型登记与之对应。入口使用CUDA与bfloat16，保留官方双向注意力和启动自检。Windows缺少融合内核时允许PyTorch数学内核，默认限制8192 tokens；`--max-model-len`可以进一步降低限制。数学内核的显存开销随输入长度平方增长，长上下文需要使用具备对应融合内核的部署环境。

该入口适配StartLux 1.1的Transformers后端。它在服务进程中选择内核，不修改模型权重、上游源码或服务协议。原始0.8B Instant只有一次选项读出，不生成思考正文。FLA或causal-conv1d的性能提示与注意力启动错误分别处理；具体是否使用加速路径由当前PyTorch环境决定。

已验证环境为Python 3.11、PyTorch 2.9.1+cu128、Transformers 5.8.1、StartLux 1.1，以及RTX 5070 Laptop 8GB。启动自检验证原因果计算保持、填充位置不影响有效内容，以及后续词元能影响前面的双向读出。运行中的服务由使用者管理，终端内按`Ctrl+C`关闭。

8192 tokens已用于验证群聊判断。Activity的输入还包含局势与行动候选，本轮五子棋样例的实际请求约9638 tokens，超过该容量。开启Activity本地决策时，需要部署能够容纳实际材料的服务，并填写相应容量；超限任务记录`context_budget_exceeded`，游戏状态保持原样。

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

Activity 将本地选择转换为[统一决定](activity-actions.md#统一决定)，保留真实选项响应及请求进一步理解的问题名称。本地直接选择的文字内心为空；沉默决定直接提交动作，需要措辞时保存交流目的和来源，需要新理解时仍由原回合调用普通模型。`intent_update` 的新增材料范围、旧意图保留及版本规则由 Activity 维护，客户端继续负责通用协议。
