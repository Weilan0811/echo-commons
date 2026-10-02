# 会话、消息与角色任务

实现位于 `modules/conversations/`。ConversationService 创建群聊或双人会话，并管理真实成员区间。离开结束原区间，重新加入建立新区间；读取资格与任务提交资格使用原区间引用。

MessageIntake 校验玩家成员资格、受众、提及与回复来源。client_message_id 在正式范围内保证重复请求返回原消息，内容变化报告冲突。消息按会话分配严格递增序号；受众和提及通过明确关联保存。

InputCollector 为同一发送者与受众合并玩家窗口内的输入。MessageQuery 按玩家视角读取可见消息；游标在过滤私有消息后仍前进，并检查所属玩家与会话。角色完整输出保存为一条权威消息；前端分成多个气泡不增加消息数量。

ConversationContext 在轮次规划事务中建立不可变 ContextSnapshot。ConversationExecution 使用原快照组装 Invocation，重试保持原输入。ConversationReview 校验当前租约、范围、来源、输出契约及消息规则；ConversationCommit 原子保存结果、回应、Thought、角色零窗口批次和轮次状态，重复提交返回已有结果。

TaskLifecycle 处理失败、取消、暂停与成员变化。角色失败不撤销同轮次其他角色的成功结果。HTTP 的请求、领域与响应分别定义，公开响应排除 Thought、内部快照和受众区间标识。

接口说明见 [服务入口](../../README.md)，完整字段见 [数据库](../database-design.md)，轮次选择见 [social](social.md)。
