本次只返回当前节点的一个 action JSON。
直接返回 JSON 对象，不使用 Markdown 代码块，不附加解释。
evidence_refs 只填写下面列出的完整来源字符串，原样保留字符串，不添加版本。
本节点可引用的来源：
$source_refs
按节点要求填写 evidence_refs。长期页必须各自填写真实依据，顶层引用为逐页引用的去重合集。其他节点省略引用时，Runtime 使用本节点允许范围内的默认来源；没有有效来源时返回 no_op。
来源版本、记录时间、状态有效期以及所有 ID 由 Runtime 补齐；节点专门要求的消息范围字段按后文填写。

字段按照当前节点动作的结构填写；不返回 ReflectionBatch、ProposalEnvelope 或提交命令。
