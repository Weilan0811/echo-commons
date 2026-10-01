# ADR-0006：模型 Provider 与档位选型

> 状态：Accepted（当前开发默认档位；S6.5 盲测结论待确定）
> 日期：2026-09-08
> 修订：v5（2026-09-08）— 收录当前模型注册、档位职责和 S4～S6 后执行的模型盲测路线
> 相关模块：Model Gateway、Agent Harness（PromptContext 投影）
> 相关文档：[Model Gateway](../modules/model-gateway.md)、[Agent Contract 与模型运行时](../infrastructure/agent-runtime.md)、[实现状态](../implementation-status.md)

## 1. 背景

S1 要求 Model Gateway 接入可替换的真实 Provider，S3/S4 随后要求角色 Identity 进入上下文组装并产出真实对话。选型必须同时满足四个约束：

1. **成本可控**：单人本地游戏，长会话，每轮重发历史，输入成本随会话长度线性增长；
2. **实时性**：玩家在等回复，输出速度直接决定体感；
3. **角色扮演质量**：治愈系陪伴游戏，中文表达自然度和情感一致性是产品生命线；
4. **结构化输出**：Provider 返回可校验的 JSON 内容，Harness 再将模型的最小回复归一化为带有 Proposal discriminator 和 Schema 版本的内部 Proposal。

现阶段不自建部署，只评估可直接调用的商业 API，后续有拓展可能。

## 2. 决策

### 2.1 当前开发档位分配

| Profile  | 模型 | 模式 | 当前入口 | 用途 |
| -------- | ---- | ---- | -------- | ---- |
| `light` | **DeepSeek V4-Flash**（`deepseek-v4-flash`） | `thinking: {type: "disabled"}` | DeepSeek 官方入口 | 日常角色演绎；分类、意图识别、轻量提取和结构化；strong 未启用时承接异步重要任务 |
| `strong` | **ZHIPU/GLM-5.3-Flash** | 由当前兼容入口默认策略决定 | 阿里千问兼容入口 | 记忆整理、反思、重要剧情演绎和其他异步高价值操作 |

业务代码只请求逻辑档位 `light` / `strong`，不硬编码供应商型号。档位到 Provider、模型、上下文上限和预算的映射由 Settings / Provider Registry 解析。

注册表同时登记 Qwen3.8-Flash 和 `MiniMax/MiniMax-M2.7` 作为评估候选；Qwen、MiniMax、GLM 使用阿里千问兼容入口，DeepSeek 使用官方入口。分类、意图识别和结构化等工作后续可由本地训练的小模型承接，但当前产品层仍只暴露 `light` / `strong` 两档语义。

### 2.2 决策依据

**`light` 使用 DeepSeek V4-Flash**：该档承担高频日常角色演绎，也覆盖分类、意图识别、轻量提取和结构化工作；在 strong 未启用时，它按显式降级策略承接 strong 的异步任务。非思考模式保留 `temperature` / `top_p` 等参数调节空间。

**`strong` 使用 ZHIPU/GLM-5.3-Flash**：该档聚焦记忆整理、反思、重要剧情演绎等异步高价值操作，允许 Runtime 为这些任务配置更高的时间和输出预算；日常短对话不因档位名称自动升级到 strong。

**成本边界**：高频日常对话优先使用 light；strong 只用于能显著影响长期体验的异步任务。分类、意图识别和结构化若由本地小模型承接，必须通过同一 Gateway 和输出校验链路，并保留可回退到 light 的路径。

### 2.3 模型盲测要求

S6.5 模型盲测在 Runtime 加固、S4 Character Agent、S5 状态和 S6 记忆完成后执行。盲测必须使用完整 Character Agent、真实任务类型和固定的 Runtime 上下文，不以单一的短对话样本决定档位。

- 盲测候选为：DeepSeek V4-Flash、Qwen3.8-Flash、`MiniMax/MiniMax-M2.7`、`ZHIPU/GLM-5.3-Flash`；
- 测试任务覆盖日常角色演绎、记忆整理、反思、重要剧情演绎、结构化输出和 strong→light 降级；
- 评价维度包括任务完成度、人格稳定性、中文自然度、情绪承接、剧情连续性、重复度、拒答/越权率、延迟、吞吐、缓存命中和单位成本；
- 盲测结论回写本 ADR 与注册表，确定后续默认档位和候选保留策略；
- 本地小模型若在盲测前完成接入，单独评估其分类、意图识别和结构化任务，不与 Character Agent 的角色质量分数混合。

### 2.4 上下文构造原则（硬约束）

Provider 的前缀缓存只从第 0 个 token 起做精确匹配：任何插在静态内容之前的动态内容，都会使其后全部内容按未命中计费。以 DeepSeek V4-Flash 为例，语义优先顺序命中率约 33%，稳定度递减顺序约 98%，单轮成本相差约 6 倍。

因此 **PromptContext 投影顺序由稳定度递减决定，不由语义优先级决定**。Harness 的输入顺序见 [Agent Contract 与模型运行时](../infrastructure/agent-runtime.md)，Gateway 侧的计量与错误边界见 [Model Gateway](../modules/model-gateway.md)。

### 2.5 用量归一化与缓存可观测性

1. **ModelResponse 必须归一化四类用量**：`input_tokens` / `cache_read_tokens` / `cache_write_tokens` / `output_tokens`。各家字段名不同，归一化是 Gateway 的职责，不得泄漏供应商字段到上层。字段对照表见 [Model Gateway §3.2](../modules/model-gateway.md)。
2. **`cache_hit_ratio` 是一等运行指标**，随每次调用写入运行日志（只写数字，不写 Prompt 或输出），并**按 Provider 分组统计**——各家的缓存保留策略从"数小时至数天"到"完全不保证"差异极大，混合统计会掩盖单家的静默失效。
3. 缓存失效是静默失败：不报错、不改延迟特征，只在账单上体现。

### 2.6 Provider 可替换

Provider 可替换是硬约束：不得在 Harness 或 Runtime 中散落任何 Provider SDK 调用。新增 Provider 必须新增适配器与合约测试。

S1 实现单一 `openai_compatible.py` 适配器即可覆盖全部候选，所有调用统一使用 OpenAI SDK，差异只在 TOML 中的 endpoint、模型名、`extra_body` 与 usage 归一化。DeepSeek 使用其官方 OpenAI-compatible endpoint；MiniMax、Qwen、GLM 使用阿里千问兼容 endpoint。入口仍由注册表管理，盲测结论负责验证任务质量、成本和稳定性。

## 3. 影响面

| 受影响对象               | 影响                                                                                    |
| ------------------------ | --------------------------------------------------------------------------------------- |
| Model Gateway            | 档位到 Provider 的映射；四类用量归一化；`cache_hit_ratio` 按 Provider 分组              |
| Agent Harness §7         | Prompt 分段顺序改为稳定度递减，已同步至 v0.6                                            |
| Context Snapshot Builder | 后续接入人格与记忆时需遵守稳定度不变量                                                  |
| S6.5 模型盲测           | 在完整 Character Agent 与 S4～S6 任务链路上验证本决策，结论回写本 ADR                 |
| S6 记忆                  | 向量召回的 top-K 必须按稳定标识重排后再拼接，不得按相关度排序                           |
| S7 巩固批                | 触发条件应为"未命中成本 × 未命中概率 > 压缩成本"或"历史已损害回复质量"，不是"超过 N 轮" |

## 4. 重新评估触发条件

- S6.5 盲测完成，任务质量、成本或稳定性不支持当前档位分配；
- `cache_hit_ratio` 持续低于 70%；
- 任一候选模型价格结构变化超过 50%（如 DeepSeek 取消闲时价、MiniMax 永久五折终止）；
- S4 badcase 集显示主力模型在人设稳定性或拒答率上不可用；
- 盲评中任一候选的实测输出速度低于 60 tok/s（实时对话的体感下限）；
- 项目进入多模态上下文阶段，需重新评估各候选的输入能力和成本。

## 5. 不作决定的事项

- Prompt 内容、Identity 写法、Memory 与 Safety 设计；
- 具体的温度、top_p 等采样参数取值（留给 S3/S4 调参）；
- 结构化输出失败的重试次数与降级策略（Harness 职责）。
