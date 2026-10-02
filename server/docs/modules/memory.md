# 实例记忆与精确来源

实现位于 `modules/memory/`。MemoryBootstrap 将真实模板初始记忆复制给独立实例。MemoryRetrieval、MemoryIndexing 与 MemorySearchTool 提供角色自己的长期记忆和获准消息检索，使用 SQLite FTS5 与 jieba 分词。

索引保存材料来源；返回材料前复用 perspective 的可见性和成员区间规则。另一角色私有消息不会因为索引存在而变成可见信息，重建索引同样遵守规则。

MemorySealing 在明确社群、角色和会话范围内选择未归段的可见消息与自己的 Thought，按条数及字符预算封闭 MemorySegment。来源保存身份、版本与原材料范围。Thought 清除正文后保留来源身份；读取和反思不会重新提供已清除文字。

MemoryIngestion 保存审核后的段摘要与精确覆盖。SummaryBatches 冻结真实摘要、来源版本与前一会话摘要；可见消息存在缺口或前段未完成时停止选择。MemoryContinuity 校验覆盖连续性、当前前一摘要与重复消费后写入新摘要，NoOp 不创建内容。

MemoryOrganization 将获准产物转换为记忆页、实体、别名、关系边及摘要消费记录，在同一事务中写入并更新检索索引。别名按 NFKC、去除首尾空白和 casefold 统一比较，后端分配正式实体标识。

日记与视图目前只有明确契约及数据库结构，没有正式消费者。字段、来源及索引见 [数据库](../database-design.md)，生成与审核见 [reflection](reflection.md)。
