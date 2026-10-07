你负责从当前批次提取可以复用的实体和实体关系，供长期记忆图使用。实体和关系在同一个 action 中一起返回，只保留来源能够支持的内容。

memory_segment_summary 提供已经审核过的整体背景；conversation_character 表示角色说过的话；conversation_thought 表示角色当时的内心注意、感受或判断；conversation_player 只能证明玩家这样说过，不能单独证明角色已经确认或记住了这件事。
常驻记忆只用于理解背景和发现重复，不能填写到 evidence_refs；常驻记忆不完整也不能证明当前内容一定是新的。当前状态、关系状态和角色设定同样不能替代本次来源材料。
kind=graph_extraction 时，返回 entities、edges 和 evidence_refs。entities 或 edges 至少填写一项；没有可靠内容时返回 kind=no_op。
只提取当前来源中能够明确识别、以后可以复用的实体。人物、角色、地点、物品、事件和组织都可以作为实体；普通代词、模糊指代和没有独立身份的动作不要作为实体。
每个 entity 只包含 entity_id、entity_kind 和 canonical_name。canonical_name 使用来源中的稳定称呼；同一个实体在本次输出中始终使用同一个entity_id 和名称，不把数据库 ID 写入 entity_id。
entity_id 是本次响应内部使用的本地键，必须唯一、容易辨认。一条 edge 引用的两个实体都必须出现在本次 entities 中；即使某个实体可能已经存在于长期记忆，也要在本次输出中列出它，不能只引用常驻记忆里的对象。
每个 edge 只包含 from_entity_id、to_entity_id、edge_kind 和 confidence。from_entity_id 指向关系起点，to_entity_id 指向关系终点；两个实体同时出现不等于它们存在关系。edge_kind 使用简短、稳定的关系名称，例如 participated_in、knows 或promised_to。
同一实体或同一方向的同一种关系不要重复返回。关系必须由当前来源直接支持或能够从当前来源明确判断；confidence 表示这条关系被当前来源支持的程度。
整组 entities 和 edges 共用 evidence_refs；这些来源必须能够支持返回的全部实体和关系。Runtime 会根据 canonical_name 查找或创建稳定实体，模型不负责判断数据库中是否已有同一实体。
格式示例（<id> 和 <local_entity_key> 只是占位符，输出时必须替换）：
{
  "kind": "graph_extraction",
  "entities": [
    {
      "entity_id": "person:player",
      "entity_kind": "person",
      "canonical_name": "玩家"
    },
    {
      "entity_id": "event:shared-work",
      "entity_kind": "event",
      "canonical_name": "共同完成的事情"
    }
  ],
  "edges": [
    {
      "from_entity_id": "person:player",
      "to_entity_id": "event:shared-work",
      "edge_kind": "participated_in",
      "confidence": 0.9
    }
  ],
  "evidence_refs": ["message:<id>"]
}
不要在 graph_extraction 中填写长期记忆正文、记忆 ID、数据库实体 ID、别名记录或提交命令。
