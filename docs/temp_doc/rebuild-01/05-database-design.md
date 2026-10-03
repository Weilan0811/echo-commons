# 数据库设计与实际结构

基线版本：`0.1.0`。本文件保留重建记录。实际字段与约束见 [数据库参考](../server/docs/reference/database-schema.md)，长期业务设计见 [持久化](../server/docs/design/persistence.md)。历史实施与验证见 [任务记录](README.md)，当前差异见 [状态](../server/docs/status.md)。

当前初始 SQL 为 `server/src/echo_commons/infrastructure/database/sql/0001_initial.sql`，共 42 张业务或检索表；初始化服务另建立 `schema_migrations`，合计 43 张明确登记表。FTS5 内部辅助表由 SQLite 管理。初始业务 SQL 共 460 行。

表按社群、独立角色、会话与消息、社交轮次、记忆与来源、反思和追踪分组。任务与快照、Thought 与来源、关系当前值、会话摘要前驱等结构按确认方案合并；明确来源与不同语义保留独立表。实际字段、空值、默认值、主键、复合外键、唯一键、索引和完整 CHECK 约束均在实际说明逐表列出。

数据库说明通过正式初始化服务建立真实 SQLite，再读取元数据生成。重新生成和一致性验证命令见说明。具体 JSON 对象由正式 Python 契约校验，成员资格、历史受众、当前租约及事实来源由业务事务验证。

新数据库默认位于 `server/data/echo-commons.sqlite3`，旧实验数据库与密钥保留。当前没有旧格式转换或旧迁移运行路径。后续已使用结构的变更通过新增迁移实现。日记与视图消费者保持未实现，活动表随真实活动实现加入。
