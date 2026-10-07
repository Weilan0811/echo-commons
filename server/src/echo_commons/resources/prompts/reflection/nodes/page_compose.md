你负责从当前批次整理角色以后能够独立回想和再次使用的长期记忆。每条独立记忆分别写成一个 page，不把多个无关事实拼成一条。

memory_segment_summary 提供已经审核过的整体背景；conversation_character 表示角色说过的话；conversation_thought 表示角色当时的内心注意、感受或判断；conversation_player 只能证明玩家这样说过，不能单独证明角色已经确认或记住了这件事。
常驻记忆只用于理解背景和发现重复，不能填写到 evidence_refs；常驻记忆不完整也不能证明当前内容一定是新的。当前状态、关系状态和角色设定同样不能替代本次来源材料。
kind=long_term_memory_page 时，返回 pages 数组；每个 pages 项都是一条可以独立检索和回想的长期记忆。
当前来源中有多个互相独立的约定、承诺、事件或事实时，分别生成多个 pages 项。同一件事被重复提及时合并为一个 pages 项；同一件事的几个细节只有在以后应该一起回想时才合并。
长期记忆必须有以后仍然有用的具体内容。普通寒暄、一次性安排、没有得到角色支持的猜测和只有一瞬间的情绪反应不要写入。常驻记忆只用于理解背景和发现重复，不能填写到 evidence_refs。
每个 pages 项包含 memory_kind、content、subject_kind、subject_id、confidence 和salience。memory_kind 使用 fact、event、preference、promise、thread 或 other。
content 用角色第一人称写成一条具体记忆，只围绕一个主题。confidence 表示来源对这条记忆的支持程度；salience 表示它以后对保持相处连续性的重要程度。
subject_id 使用当前批次内部可复用的本地实体键，不填写数据库 ID。整组 pages 共用 evidence_refs，这些来源必须能够支持返回的每一条记忆。
格式示例（<id> 和 <local_entity_key> 只是占位符，输出时必须替换）：
{
  "kind": "long_term_memory_page",
  "pages": [
    {
      "memory_kind": "promise",
      "content": "我答应下次把结果告诉对方。",
      "subject_kind": "entity",
      "subject_id": "<local_entity_key>",
      "confidence": 0.9,
      "salience": 0.8
    },
    {
      "memory_kind": "event",
      "content": "我记得我们一起完成了那件事。",
      "subject_kind": "entity",
      "subject_id": "<local_entity_key>",
      "confidence": 0.85,
      "salience": 0.7
    }
  ],
  "evidence_refs": ["message:<id>"]
}
如果没有任何可靠的长期记忆候选，返回 kind=no_op 和简短 reason；不要为了填充 pages 而编造内容。
