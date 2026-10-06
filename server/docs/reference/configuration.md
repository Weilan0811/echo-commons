# 配置参考

## 1. 设置文件及路径

基础、故事与校准使用任务路由键 character_authoring，未指定时使用当前默认模型。采访使用与 conversation_reply 相同的模型；明确配置 character_interview 后使用该路由。与对话和反思共享 workers.model_concurrency。当前作者调用固定截止 90 秒、最多两次逻辑请求及每次最多 6000 输出 tokens（模型输出单位），供应商重试沿用对应 ModelEntry；不增加独立凭据或模型客户端。

CLI 默认读取 `config/settings.toml`，使用 `echo-commons --settings <路径> serve` 指定文件。文件顶层必须 `schema_version = 1`。下面按正式文件分组列出所有 Settings 字段；空值表示没有覆盖。

数据库、人物资源、模型登记、密钥、日志和捕获相对路径，以设置文件所在目录解析，`~` 展开为用户目录。显式填写和省略后采用的默认路径使用同一规则；切换启动目录不改变同一配置文件的解释。identity.root 为空时使用包内资源。

## 2. 全部设置

| TOML 组及字段 | 默认值 | 范围和作用 |
|---|---|---|
| server.environment | development | 环境名称 |
| server.host | 127.0.0.1 | 监听地址 |
| server.port | 8765 | 1—65535 |
| server.cors_origins | 空数组 | 浏览器允许来源，完整协议、域名和端口 |
| storage.database_path | ../data/echo-commons.sqlite3 | SQLite 路径 |
| identity.root | 空值 | 空值读取包内人物资源；指定时必须真实存在且合法 |
| model.registry_path | model-registry.toml | 模型登记 |
| model.secrets_path | model-secrets.toml | 独立密钥 |
| workers.enabled | true | 启用后台工作 |
| workers.poll_interval_seconds | 0.25 | 大于 0 |
| workers.shutdown_timeout_seconds | 30 | 大于 0，关闭等待期限 |
| workers.model_concurrency | 3 | 至少 1，共享模型额度 |
| task.lease_seconds | 90 | 大于 0 |
| task.lease_heartbeat_interval_seconds | 5 | 大于 0，必须小于租约减安全余量 |
| task.lease_safety_margin_seconds | 2 | 至少 0 |
| task.max_agent_attempts | 3 | 至少 1，持久执行次数 |
| task.retry_backoff_seconds | 1 | 至少 0 |
| social.quiet_window_seconds | 6 | 至少 0，玩家窗口；角色批次固定为 0 |
| social.max_responders | 2 | 至少 1 |
| context.recent_message_limit | 20 | 至少 1 |
| context.recent_message_max_chars | 6000 | 至少 1 |
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
| observability.log_level | INFO | 日志级别 |
| observability.log_path | 空值 | 模板为 ../data/logs/echo.log |
| observability.log_max_bytes | 5242880 | 至少 1 |
| observability.log_backup_count | 3 | 至少 0 |
| observability.debug_capture_enabled | false | 保存完整私有调试材料 |
| observability.debug_capture_path | ../data/debug-captures | 调试捕获目录 |
| observability.trace_retry_backoff_seconds | 1 | 至少 0 |
| observability.trace_max_attempts | 5 | 至少 1 |
| observability.trace_lease_seconds | 30 | 大于 0 |
| observability.trace_batch_size | 25 | 至少 1 |

加载器逐组检查上表规定的字段，未知组、未知字段和放错组的字段明确拒绝。conversation.generation 与 reflection.generation 只允许 temperature、top_p、max_output_tokens，且必须使用 TOML 表格。精确类型及约束还可查看生成的 [Settings schema](settings-schema.json)。

各预算分别保护材料输入、输出候选、循环步骤、网络请求和期限。增加输出 token 额度不会放宽正文字符上限。工具往返和格式修正计入同一节点执行预算。

## 3. 模型登记

模型文件顶层 `schema_version = 1`。`runtime.backend` 只接受 openai_compatible，`active_profile` 指定未显式路由任务的模型组。`profiles` 将 light、strong 等组映射到 entries 标识；`routing.task_profiles` 将 conversation_reply、reflection 映射到模型组。`strong_enabled=false` 时 strong 路由转为 light，属于用户策略，调用失败不会自动改变它。

gateway 提供 request_timeout_seconds（默认 25，大于 0）、max_retries（默认 1，至少 0）、retry_backoff_seconds（默认 0.5，至少 0）、max_output_tokens（默认 512，至少 1）、response_format（默认 json_object，允许空字符串）。这些是加载器默认；项目登记的 gateway 当前覆盖为 60 秒、20480 token。

entries 每项必填 model_vendor、model、base_url（HTTP/HTTPS）、credential_ref、access_route。可选 enabled 默认 true，供应商期限、重试、退避、token、temperature、top_p、response_format 和 extra_body 可独立覆盖。生成参数优先级为任务设置、模型条目、供应商默认；extra_body 是供应商特定字段，不进入业务契约。

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
