# 模块索引

| 模块 | 职责与入口说明 |
|---|---|
| communities | [社群、玩家与成员](community.md) |
| characters | [模板、独立实例、状态与关系认识](character.md) |
| conversations | [会话、权威消息、输入与角色任务](conversation.md) |
| social | [轮次、参与决定与完成](social.md) |
| perspective | [客观世界与共同读取资格](perspective.md) |
| memory | [角色记忆、来源、摘要与检索](memory.md) |
| reflection | [反思图、节点、产物与事实提交](reflection.md) |
| agents | [正式执行循环](agent-harness.md) |
| models | [真实模型网关](model-gateway.md) |

每个模块的纯规则位于自己的 domain；读取与持久化由该模块负责。跨模块通过 contracts 中的明确读取或事实写入端口合作。HTTP 字段查看对应模块 api/schemas.py；持久字段统一查看 [数据库说明](../database-design.md)。
