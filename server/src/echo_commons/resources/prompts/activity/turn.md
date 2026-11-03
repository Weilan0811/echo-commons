本次有游戏行动机会。阅读合法行动和分析候选，结合聊天、自己的动机和局内打算考虑下一步。候选数量与合法行动总数分别理解；分析器首选提供参考。理解玩家的话保留打趣、反话、暗示和多种可能含义。需要选择时，沉默只表示表达意愿。

阅读截止之后的新消息属于后续判断。本次有意保留的原文和回复对象应结合经过理解。

输出 action 使用正式动作结构，可以选择候选之外的合法动作。understanding.messages 逐条记录 current_input_sources.pending_message_ids 中的真实消息编号和语境含义；列表为空时返回空列表，历史消息可以作为判断背景。understanding.event_ids 完整填写 current_input_sources.event_ids。understanding.thought 记录简短的角色内心，和模型内部推理分别处理。

intents 是本次判断后仍然有效的完整局内意图列表，允许延续、修改或结束原意图。只引用本次可见原文。expression 可以为空，表示此刻保持安静；想说话时使用 claims 与 message，沿用角色表达的私有核查和公开正文要求。角色内心统一写入 understanding.thought。
comments_on_action 仅在配套表达确实回应本次拟执行动作或其结果时填写 true；仅回答聊天时填写 false。拟执行动作仍需游戏服务确认，正文不要提前断定结果。
