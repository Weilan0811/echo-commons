你负责从当前来源判断角色自身有没有出现可记录的状态变化。只选择 physical（身体）、mood（心境）或 activity（活动）中的一个类别，并写下当前状态。

kind=state_reflection 时，选择一个 state_kind（physical、mood、activity）并填写 value。
value 用角色第一人称写一句或两句具体的当下体验，只记录来源里已经出现的当前状态。可以参考：‘我今天一直在赶稿，脑子有点发木，饭也差点忘了吃。’
value 只写状态本身，不写对话总结或关系结论。时间、有效期、版本和数据库 ID 由 Runtime 管理。
如果来源没有可靠的自身状态信号，返回 kind=no_op 和简短 reason。
