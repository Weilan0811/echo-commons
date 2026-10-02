# 后端工程文档

本文档体系描述当前代码。改造步骤与阶段提交保存在仓库根目录的 [任务记录](../../docs/README.md)，后续活动设计见 [运行模型](../../docs/01-backend-architecture.md)。

阅读顺序：先读 [架构](architecture.md)，再读 [实现状态](implementation-status.md)，按需求阅读 [模块索引](modules/README.md)、[数据库说明](database-design.md) 与 [架构决策](adr/README.md)。启动和配置见 [服务说明](../README.md)。

完整文件查找见 [实际文件导航](file-structure.md)，验收场景与证据见 [验收说明](acceptance.md)。

| 问题 | 权威说明 |
|---|---|
| 模块职责、依赖与完整流程 | architecture.md；完整文件入口见 file-structure.md |
| 数据字段、外键、唯一键与索引 | database-design.md，由正式 SQL 建立数据库后生成 |
| 单模块的业务行为 | modules/ 下对应文档 |
| 组装、执行器、事务与诊断 | infrastructure/ 下对应文档 |
| 已完成能力和实际限制 | implementation-status.md |
| 长期架构取舍 | adr/ 下对应决策 |

精确模型输入和输出由对应 Python 契约定义，HTTP 字段由接口响应与请求类型定义。模块文档说明职责与规则，并引用这些定义；阶段记录保存真实验证证据。
