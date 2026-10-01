# ADR-0001：本地 SQLite 与持久化 Turn Runtime

> 状态：Accepted  
> 日期：2026-08-31
> 后续决策：工作项从 `conversation_turns` 收敛为 ConversationTask/AgentResult 的过程见 [0007](0007-conversation-batching-and-response-eligibility.md)；旧 M0 持久化表的最终清理见 [0008](0008-remove-legacy-m0-persistence.md)；反思任务与独立 Worker 的边界见 [0009](0009-reflection-worker-boundary.md)。本 ADR 仍约束本地 SQLite、单进程 Runtime、进程内唤醒和事务外 Agent 调用。

## 背景

Echo 当前是本地运行、单账号、单进程的游戏项目。会话请求必须在服务重启后恢复，同时不能为了后台 Agent 调用让 HTTP 请求长期阻塞。引入 Redis、Celery 或外部消息队列会增加部署与数据一致性成本。

## 决策

1. 使用单个 SQLite 文件作为后端唯一持久层。
2. 使用 `conversation_turns` 保存待处理、处理中、重试和终态工作。
3. 进程内 `asyncio.Event` 只负责唤醒，不保存工作事实。
4. FastAPI lifespan 拥有唯一 Conversation Worker。
5. 进程内写事务串行；Agent 调用期间不持有写事务。
6. 使用租约识别崩溃遗留的 processing Turn，并在启动或后续领取时恢复。

## 结果

正面影响：

- 无额外基础设施，安装和备份边界清晰；
- HTTP 接受与 Agent 处理可靠解耦；
- 进程崩溃后可以从数据库恢复；
- Runtime 可用 Stub 离线集成测试。

限制：

- 当前实现不支持多进程 Worker；
- SQLite 写入仍是串行资源；
- 长 Agent 调用需要租约时限或后续心跳机制；
- 多账号或远程部署时必须重新评估调度和数据库方案。

## 重新评估条件

- 需要多进程或多主机 Worker；
- 单文件数据库无法满足容量、备份或并发要求；
- 服务从本机组件变为共享在线服务；
- 任务类型和调度规模明显超出单进程 Runtime。
