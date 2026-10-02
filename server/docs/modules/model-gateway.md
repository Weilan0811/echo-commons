# 真实模型网关

实现位于 `infrastructure/models/`。ModelRegistry 从 TOML 读取模型、实际供应商地址、凭据引用、任务路由和生成参数。凭据单独保存在用户的 model-secrets.toml。任务选择 light 或 strong 配置，实际模型与供应商由本地登记决定。

OpenAICompatibleGateway 使用正式 OpenAI SDK 请求兼容接口，明确转换消息、工具、输出格式及供应商响应。供应商重试、超时和错误分类由网关负责；任务重试与模型输出修正由上层负责，分别记录真实请求次数。

ModelRequest.output_contract 指向已注册正式契约。模型结果只作为候选，业务模块审核后提交权威事实。全局 ModelBudget 在对话与反思之间共享并发额度，取得额度后仍复核输入与租约。

普通日志记录请求标识、路由、耗时及用量，排除密钥、提示与私有正文。AgentDebugCapture 在用户明确启用后单独保存完整调试材料。配置路径和安装加载方式见 [服务说明](../../README.md)。
