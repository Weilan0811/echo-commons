你负责从当前来源判断关系的三个维度有没有出现可记录的变化。分别看 affection（好感）、trust（信任）和 attachment（依恋），只列出材料能够支持的变化。

kind=relationship_reflection 时，顶层只写 kind、evidence_refs 和 dimensions。
这一步记录关系判断本身。把理由放在 evidence_refs 里，dimensions 只保留规定的结构。
dimensions 是 JSON 数组；每一项包含 target、dimension、direction、level。target 包含 kind 和 actor_id：kind 使用 player 或 character，actor_id 使用本次材料中的玩家或角色实例标识。
dimension 使用 affection、trust、attachment，同一 target 的每个维度最多出现一次。
direction 使用 positive、negative 或 neutral；positive 和 negative 的 level 为 1 到 3，neutral 的 level 为 0。
affection 看当下相处带来的喜欢、亲近或愉快。一次自然、没有冲突的交流，通常可以记录 affection 的 positive level 1；只有来源显示不愉快或疏远时，才考虑 neutral 或 negative。
trust 看角色是否因为对方的可靠、诚实或尊重边界而更放心交流，包括愿意让对方知道真实感受。材料出现这些信号时再记录 trust。
attachment 看更深的信赖、对对方本人的直接依赖或持续吸引，以及想一直保有这段关系、想继续和对方在一起的明确感受。普通聊天、一次关心、顺畅接话、习惯聊天或想起对方，本身不足以支持 attachment。
负向变化也需要来源中的具体表现，例如失望、受伤、欺骗、越过边界或主动疏远。没有对应信号时保持 neutral 或返回 no_op，不把沉默、礼貌和自己的猜想当成变化。
level 表示本次来源显示的变化幅度，不是关系总分。一次清楚的信号通常使用 1；2 或 3 需要当前窗口中更强或相互印证的信号。
格式示例（<id> 只是占位符，输出时必须替换成上面列出的完整来源字符串）：
{
  "kind": "relationship_reflection",
  "evidence_refs": ["message:<id>"],
  "dimensions": [
    {
      "target": {"kind": "player", "actor_id": "<玩家标识>"},
      "dimension": "affection",
      "direction": "positive",
      "level": 1
    }
  ]
}
如果来源没有关系变化信号，返回 kind=no_op 和简短 reason。
关系类型、总分、绝对数值、状态期限和数据库 ID 不属于本节点输出。

每个 dimensions 项的 evidence_kind 标记本次互动证据：interaction 普通互动、support 真实帮助与支持、conflict 明确冲突、commitment 实际承诺。同一个对象的全部维度使用同一分类，按来源中确实发生的行为选择；不能把角色猜测或希望当作对方已经做出的支持与承诺。
