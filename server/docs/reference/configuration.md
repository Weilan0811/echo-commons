# 配置参考

## 1. 设置文件及路径

文本供应商支持DeepSeek、DashScope和MiniMax，均使用现有OpenAI兼容网关。`profiles.light`指定主力条目，`routing.strong_enabled`默认`false`。关闭增强时，指向`strong`的任务使用`light`，允许仅保留主力条目与凭据；开启后需要配置`profiles.strong`。`inspect`展示实际任务路由、模型、凭据引用及是否已配置，不发出模型请求。

随包推荐条目为`deepseek_flash`、`qwen_flash`、`minimax_flash`。用户可在同一协议家族内填写其他型号和地区端点。供应商参数在`infrastructure/models/factory.py`集中转换，失败重试沿用原模型。MiniMax M3的思考保持开启，默认`reasoning_effort=low`（低思考深度），不发送其不支持的采样参数。

基础、故事与校准使用任务路由键 character_authoring，未指定时使用当前默认模型。采访草稿使用与 conversation_reply 相同的模型；明确配置 character_interview 后使用该路由。采访检查使用 character_interview_review，随包默认 strong，遵守 strong_enabled 策略，reasoning_effort=low。两种实际模型组、思考深度和提示一起冻结。与对话和反思共享 workers.model_concurrency。当前作者调用固定截止 90 秒、最多两次逻辑请求及每次最多 6000 输出 tokens（模型输出单位）；采访使用第二次请求核查事实与表达，其他操作按需修正无效输出。供应商重试沿用对应 ModelEntry；不增加独立凭据或模型客户端。

CLI 默认读取 `config/settings.toml`，使用 `echo-commons --settings <路径> serve` 指定文件。文件顶层必须 `schema_version = 1`。下面按正式文件分组列出所有 Settings 字段；空值表示没有覆盖。

数据库、人物资源、模型登记、密钥、日志和捕获相对路径，以设置文件所在目录解析，`~` 展开为用户目录。显式填写和省略后采用的默认路径使用同一规则；切换启动目录不改变同一配置文件的解释。identity.root 为空时使用包内资源。

## 2. 全部设置

`memory.vector.enabled` 默认 false。关闭时不需要向量模型，不创建向量客户端或索引任务。开启时，`memory.vector.profile` 指向模型登记中独立的向量模型配置，密钥沿用现有凭据管理；对话模型不会自动充当向量模型。`dimensions` 必须等于实际返回维度。后台调用共享模型额度，按后台整理份额获得机会；每份失败材料保存原因，修正配置后可通过管理接口重建索引。

全局调度使用 `workers.turn_weight`、`workers.exchange_weight`、`workers.background_weight`。已有自定义设置文件中的 `activity_task_weight`、`activity_expression_weight` 需要替换为这三个字段，默认值为 2、2、1；密钥和模型登记保持原配置。

| TOML 组及字段 | 默认值 | 范围和作用 |
|---|---|---|
| server.environment | development | 环境名称 |
| server.host | 127.0.0.1 | 监听地址 |
| server.port | 8765 | 1—65535 |
| server.cors_origins | 空数组 | 浏览器允许来源，完整协议、域名和端口 |
| storage.database_path | ../data/echo-commons.sqlite3 | SQLite 路径 |
| storage.asset_directory | ../data/assets/images | 图像资产目录，以设置文件目录解析 |
| images.base_url | https://api.apimart.ai/v1 | APIMart 接口地址 |
| images.model | gpt-image-2 | 图像模型 |
| images.credential_ref | apimart | 现有凭据文件中的引用名，允许空值，申请时报告不可用 |
| images.concurrency | 1 | 至少 1，独立生图并发 |
| images.poll_interval_seconds | 5 | 大于 0，供应商任务查询间隔 |
| images.request_timeout_seconds | 30 | 大于 0，单次网络请求期限 |
| images.task_timeout_seconds | 900 | 大于 0，从申请开始的任务总期限 |
| identity.root | 空值 | 空值读取包内人物资源；指定时必须真实存在且合法 |
| activity.input_max_chars | 32000 | 至少 1；活动完整输入的字符预算，两种模型材料均检查 |
| activity.persona_direct_max_chars | 6000 | 至少 1；静态人物三份资料合计不超过此值时直接用于本地判断 |
| activity.persona_projection_max_chars | 4000 | 至少 1；较长人物资料精简后的合计字符上限，按来源版本复用 |
| activity.event_limit | 100 | 1—200；单次冻结读取的游戏事件数量上限 |
| activity_reactions.quiet_seconds | 60 | 大于 0；距最近消息或行动达到此秒数后形成一次安静机会 |
| activity_reactions.minimum_gap_seconds | 10 | 至少 0；普通主动机会距最近消息的最短间隔 |
| activity_reactions.frequency_window_seconds | 90 | 大于 0；统计近期正式角色消息的时间窗口 |
| activity_reactions.quiet_saturation_seconds | 90 | 大于 0；概率公式中安静程度达到上限所需秒数 |
| activity_reactions.recency_saturation_seconds | 30 | 大于 0；概率公式中近期消息抑制结束所需秒数 |
| activity_reactions.base_probability | 0.05 | 0—1；普通事件的基础机会参数 |
| activity_reactions.significance_weight | 0.55 | 至少 0；实际事件重要程度的权重 |
| activity_reactions.quiet_weight | 0.30 | 至少 0；安静程度的权重 |
| activity_reactions.maximum_probability | 0.9 | 0—1；普通机会概率上限，正式结算独立处理 |
| activity_reactions.frequency_divisor | 2 | 大于 0；近期角色发言数量的抑制尺度；公式见[局内表达](../design/activity-expression.md) |
| game_analysis.rapfi.directory | ../data/game-analysis/rapfi/250615 | 固定程序、配置与权重目录，相对于设置文件目录解析 |
| game_analysis.rapfi.executable | 空值 | 按系统选择官方发布程序；可填写同版其他程序的文件名 |
| game_analysis.rapfi.threads | 1 | 1—256，单个引擎进程线程数 |
| game_analysis.rapfi.hash_memory_mb | 64 | 至少 1，散列表预算；不含权重等进程内存 |
| game_analysis.rapfi.search_time_ms | 500 | 40—60000，一次玩法分析的搜索预算，有缺失建议时在两次搜索之间分配 |
| game_analysis.rapfi.candidates | 6 | 1—32，展示候选数量上限，独立于合法动作总数 |
| game_analysis.rapfi.timeout_seconds | 10 | 大于 0，进程准备与单次协议调用的实际期限；失败按 task.max_agent_attempts 有限重试 |
| model.registry_path | model-registry.toml | 模型登记 |
| model.secrets_path | model-secrets.toml | 独立密钥 |
| workers.enabled | true | 启用后台工作 |
| workers.poll_interval_seconds | 0.25 | 大于 0 |
| workers.shutdown_timeout_seconds | 30 | 大于 0，关闭等待期限 |
| workers.model_concurrency | 3 | 至少 1，共享任务执行器数量及模型调用额度 |
| workers.turn_weight | 2 | 至少 1；游戏回合的任务领取和模型额度份额 |
| workers.exchange_weight | 2 | 至少 1；普通聊天、局内回应及独立表达的任务领取和模型额度份额 |
| workers.background_weight | 1 | 至少 1；后台整理的任务领取和模型额度份额 |
| memory.vector.enabled | false | 可选向量服务开关 |
| memory.vector.profile | embedding | 模型登记中的独立向量配置 |
| memory.vector.dimensions | 1536 | 至少 1；实际返回维度 |
| memory.vector.batch_size | 16 | 1—128；每次索引材料数 |
| memory.vector.batch_max_chars | 16000 | 至少 1；每次向量请求的正文预算 |
| memory.vector.timeout_seconds | 30 | 大于 0；包含等待额度与重试的期限 |
| memory.retrieval.automatic_limit | 5 | 1—50；自动检索条数上限 |
| memory.retrieval.automatic_max_chars | 4000 | 至少 1；自动检索正文预算 |
| memory.retrieval.input_max_chars | 32000 | 至少 1；实际对话提示的共同字符预算 |
| memory.retrieval.candidate_limit | 100 | 至少 1；排名融合候选上限 |
| memory.context.current_ratio | 0.6 | 大于 0、小于 1；当前会话历史的目标份额 |
| memory.context.nearby_ratio | 0.3 | 至少 0、小于 1；临近场景的目标份额；两项合计必须小于 1，余额供较早相关记忆 |
| memory.cycles.scan_seconds | 30 | 大于 0；大小循环共同扫描间隔 |
| memory.cycles.experience_idle_seconds | 600 | 大于 0；每个会话及成员区间独立计算的静默秒数 |
| memory.cycles.summary_target_chars | 12000 | 至少 1；各消费者新摘要的触发量 |
| memory.cycles.summary_wait_seconds | 7200 | 大于 0；最早可消费摘要的最长等待时间 |
| task.lease_seconds | 90 | 大于 0 |
| task.lease_heartbeat_interval_seconds | 5 | 大于 0，必须小于租约减安全余量 |
| task.lease_safety_margin_seconds | 2 | 至少 0 |
| task.max_agent_attempts | 3 | 至少 1，持久执行次数 |
| task.retry_backoff_seconds | 1 | 至少 0 |
| social.quiet_window_seconds | 6 | 至少 0，玩家窗口；角色批次固定为 0 |
| social.max_chain_messages | 3 | 至少 1，每链正式角色消息数量上限 |
| social.max_chain_tasks | 6 | 至少 1，每链已创建角色任务数量上限 |
| context.recent_message_limit | 20 | 至少 1；旧输入及尚未更新的活动准备使用，新聊天按实际容量选择 |
| context.recent_message_max_chars | 6000 | 至少 1；适用范围同上 |
| context.covered_message_overlap | 4 | 至少 0，摘要覆盖后的重叠消息 |
| context.resident_memory_limit | 32 | 至少 1 |
| context.memory_search_max_results | 5 | 1—5，与工具查询上限一致 |
| conversation.max_thought_length | 1000 | 至少 1 |
| conversation.max_utterance_length | 2000 | 至少 1 |
| conversation.generation.temperature | 空值 | 0—2 |
| conversation.generation.top_p | 空值 | 大于 0、至多 1 |
| conversation.generation.max_output_tokens | 空值 | 至少 1 |
| reflection.generation.temperature | 空值 | 0—2 |
| reflection.generation.top_p | 空值 | 大于 0、至多 1 |
| reflection.generation.max_output_tokens | 空值 | 至少 1 |
| reflection.max_model_steps | 4 | 至少 1 |
| reflection.max_model_requests | 4 | 至少 1 |
| reflection.execution_timeout_seconds | 300 | 大于 0 |
| reflection.max_materials | 256 | 至少 1 |
| reflection.max_material_chars | 20000 | 至少 1 |
| reflection.max_messages_per_segment | 100 | 至少 1 |
| reflection.max_candidates | 64 | 至少 1 |
| reflection.max_output_chars | 20000 | 至少 1 |
| reflection.core_memory_max_chars | 600 | 1～6000；核心记忆提示、修正与审核共用上限 |
| reflection.relationship_attitude_max_chars | 300 | 1～3000；关系描述提示、修正与审核共用上限 |
| reflection.initialization_max_candidates | 256 | 至少 1；初始化候选上限 |
| reflection.initialization_max_output_chars | 160000 | 至少 1；初始化正文上限 |
| reflection.initialization_chars_per_input_char | 6 | 至少 1；输入正文与输出预算比例 |
| reflection.initialization_candidates_per_material | 8 | 至少 1；每份材料的候选额度 |
| observability.log_level | INFO | 日志级别 |
| observability.log_path | 空值 | 模板为 ../data/logs/echo.log |
| observability.log_max_bytes | 5242880 | 至少 1 |
| observability.log_backup_count | 3 | 至少 0 |
| observability.debug_capture_enabled | false | 保存请求前的完整 JSON 与易读文本，以及实际响应；生产环境不启用 |
| observability.debug_capture_path | ../data/debug-captures | 调试捕获目录 |
| observability.trace_retry_backoff_seconds | 1 | 至少 0 |
| observability.trace_max_attempts | 5 | 至少 1 |
| observability.trace_lease_seconds | 30 | 大于 0 |
| observability.trace_batch_size | 25 | 至少 1 |

加载器逐组检查上表规定的字段，未知组、未知字段和放错组的字段明确拒绝。conversation.generation 与 reflection.generation 只允许 temperature、top_p、max_output_tokens，且必须使用 TOML 表格。精确类型及约束还可查看生成的 [Settings schema](settings-schema.json)。

各预算分别保护材料输入、输出候选、循环步骤、网络请求和期限。增加输出 token 额度不会放宽正文字符上限。工具往返和格式修正计入同一节点执行预算。

初始化预算的计算、节点分配与引用统计规则见 [记忆设计](../design/memory.md#21-初始化预算与来源引用)。

## 3. 模型登记

模型文件顶层 `schema_version = 1`。`runtime.backend` 只接受 openai_compatible，`active_profile` 指定未显式路由任务的模型组。`profiles` 将 light、strong 等组映射到 entries 标识；`routing.task_profiles` 将 conversation_reply、reflection 映射到模型组。`strong_enabled=false` 时 strong 路由转为 light，属于用户策略，调用失败不会自动改变它。

gateway 提供 request_timeout_seconds（默认 25，大于 0）、max_retries（默认 1，至少 0）、retry_backoff_seconds（默认 0.5，至少 0）、max_output_tokens（默认 512，至少 1）、response_format（默认 json_object，允许空字符串）。这些是加载器默认；项目登记的 gateway 当前覆盖为 60 秒、20480 token。

entries 每项必填 model_vendor、model、base_url（HTTP/HTTPS）、credential_ref、access_route。可选 enabled 默认 true，供应商期限、重试、退避、token、temperature、top_p、response_format 和 extra_body 可独立覆盖。生成参数优先级为任务设置、模型条目、供应商默认；extra_body 是供应商特定字段，不进入业务契约。

每个模型条目可设置 `context_window_tokens`（默认 131072）和 `token_counter`（默认 `utf8_bytes`），容量必须大于该条目的输出上限。容量是本应用允许使用的上限，应不超过实际服务配置；随包 StartLux 使用 65536，其他示例条目使用 131072。`utf8_bytes` 采用文本 UTF-8 字节数作为保守 token 上界；`cl100k_base`、`o200k_base` 使用 tiktoken，对应实际模型编码时再选用。未知模型不自动套用其他模型的分词器。

新聊天固定模型条目、实际输出预留和共同字符预算，默认对话输出预留仍为 4096。开启本地判断时，共同材料同时满足本地与普通模型限制。需要整理历史才能满足容量时，任务等待既有摘要流程，恢复继续使用原来源截止；当前输入本身超限时明确失败。工具调用和格式修正后，网关继续检查每次完整请求。

```toml
schema_version = 1
[runtime]
backend = "openai_compatible"
active_profile = "light"
[gateway]
request_timeout_seconds = 60
max_retries = 1
max_output_tokens = 2048
[profiles]
light = "chat"
strong = "chat"
[routing]
strong_enabled = true
[routing.task_profiles]
conversation_reply = "light"
reflection = "strong"
[entries.chat]
model_vendor = "deepseek"
model = "deepseek-v4-flash"
base_url = "https://api.deepseek.com"
credential_ref = "deepseek"
access_route = "direct"
```

密钥文件独立写入 `[credentials]`，字段名与 credential_ref 一致，值为实际凭据。此文件被 Git 忽略。空值或没有凭据可以完成初始化和只读检查，实际模型调用明确失败。未知路由、缺少模型、禁用条目或非法地址导致配置错误；程序不生成替代模型结果。

完整正式模板在 [settings.toml](../../config/settings.toml)、[model-registry.toml](../../config/model-registry.toml) 和 [密钥格式示例](../../config/model-secrets.example.toml)。示例只说明格式，不要求修改用户实际路由。

群聊接话配置在创建链条时固定，修改配置只影响新链。`social.max_responders` 已移除，外部旧配置需要删除该字段；同会话有效任务固定为一名角色。私聊保持一次回应。完整预算和停止含义见 [会话设计](../design/conversation-and-social.md#6-回应受众与停止规则)。
