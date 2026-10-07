本次只返回当前节点的一个 action JSON。
evidence_refs 只填写下面列出的完整来源字符串，原样保留字符串，不添加版本。
本节点可引用的来源：
$source_refs
省略 evidence_refs 时，Runtime 会使用本节点允许范围内的默认来源；没有有效来源时返回 no_op。
来源版本、记录时间、状态有效期以及所有 ID 由 Runtime 补齐；节点专门要求的消息范围字段按后文填写。

正文保持角色第一人称，字段按照当前节点动作的结构填写；不返回 ReflectionBatch、ProposalEnvelope 或提交命令。
