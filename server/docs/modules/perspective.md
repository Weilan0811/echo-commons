# 客观世界观察

实现位于 `modules/perspective/`。ObservationScope 明确社群、会话、观察者与消息上限。ConversationPerspective 使用实际成员区间和消息接收者判断可见性；WorldPerspective 组合会话观察与客观角色身份。

客观内容包括可见消息、参与者、会话及社群环境。角色自己的状态、主观关系和长期记忆由 characters 与 memory 提供，再由任务输入组装器组合。未来棋局与场景视图通过 WorldReader 的明确适配扩展。

对话上下文、消息读取、记忆检索、材料归段与反思输入复用相同观察规则。消息上限冻结历史视角；加入前、离开后和重新加入的读取严格使用对应成员区间。检索索引只提供候选来源，返回前仍执行正式可见性验证。

本模块没有第二套权威事实表，也不写入角色记忆。跨模块读取端口位于 contracts.py；实际消息和成员事实由 [conversations](conversation.md) 管理。
