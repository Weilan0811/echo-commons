# 人物模板与独立角色

实现位于 `modules/characters/`。BlueprintCatalog 加载作者定义的真实人物资源。模板版本为 `0.1.0`，明确包含身份、声音风格、初始记忆和能力；加载规则与实例初始化相互独立。

CharacterBootstrap 根据模板创建角色实例，写入属于该实例的状态与初始记忆，再加入社群。相同模板可以在同一社群或不同社群创建多个实例，各自保存角色标识、状态、关系认识、记忆和任务。模板内容不会成为共享可变状态。

CharacterContext 组装角色自己的身份、声音风格、状态和主观关系。CharacterIdentity 提供客观展示身份。CharacterRegistry 根据模板能力建立实际 Agent 与工具权限。取消检索能力会同时移除模型可见工具定义和执行授权。

CharacterStateService 管理可用状态及人物状态事实。关系证据按 ActorRef 明确指向玩家或其他角色，RelationshipPolicy 处理亲近、信任、依赖等正式维度，技术失败保存于任务诊断。

模板目录、services、repositories 与 domain 分别承担加载、编排、存储及纯规则。公开实例响应只提供登记和可用状态。字段见 [数据库](../database-design.md)，主观信息与客观信息的边界见 [观察](perspective.md)。
