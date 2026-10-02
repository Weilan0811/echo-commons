# 实例运行范围与输出边界

InvocationScope 明确社群、角色、会话与任务。输入、执行策略与输出契约由具体任务准备器建立，保存在正式任务快照中。对话与反思共享调用协议，各自保留具体来源、动作空间和读取政策。

角色身份使用独立实例标识；玩家或其他角色通过 ActorRef 区分。模型不能选择另一实例的私有读取范围。对话执行输出 CharacterMessageProposal，反思节点输出注册的具体 Action；两者通过正式业务审核后才能修改权威状态。

运行用量、失败类别与恢复动作用于真实诊断和重试。任务事实由所属模块保存，AgentRunResult 的成功状态本身不会修改消息或记忆。契约文件见 agents/contracts，执行循环见 [Agent Harness](../modules/agent-harness.md)。
