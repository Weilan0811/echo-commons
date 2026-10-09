# SSE 后端实施方案（临时）

更新日期：2026-10-09。用途：代码修改前的最后确认与实施跟踪。后端实现、验收和正式文档同步完成后删除本文件。

## 1. 授权范围与当前状态

本轮仅修改后端代码与后端文档，不修改 frontend/ 下的代码、类型或文档，不实现活动玩法。角色消息保持完整生成、审核和保存后展示；管理查询与后台任务检查保持原职责。方案依据为 [实时通信设计](design/realtime-communication.md) 和 [ADR 0009](adr/0009-http-and-sse-communication.md)。

| 能力 | 当前状态 | 本轮交付 |
|---|---|---|
| HTTP 消息写入、历史与增量读取、轮次查询 | 已实现 | 保留现有字段与行为，作为初始读取和恢复入口 |
| 玩家可见范围、成员区间、幂等及短事务 | 已实现 | 推送复用相关业务规则 |
| 社群、会话、成员、阅读位置查询与写入 | 已实现 | 实际变化产生通知 |
| SSE 连接、心跳和断线补充 | 待实现 | 按社群与玩家建立统一事件流 |
| 持久事件与清理边界 | 待实现 | 新迁移、24 小时保留、每小时清理 |
| 业务提交后唤醒 | 待实现 | 同步 HTTP 与异步执行共同使用 |
| 前端停止轮询并接入 SSE | 本轮范围外 | 后端交付接入契约与说明，前端分支另行实施 |
| 活动规则、活动事件和接口 | 本轮范围外 | 正式设计规定复用方式，不预建玩法接口或空注册项 |

本次文档修订未改变实际实现状态；当前最高数据库版本仍为 10，OpenAPI 仍只包含现有接口。

## 2. 新接口与事件契约

### 2.1 初始位置

`GET /api/communities/{community_id}/events/cursor?player_id=alice`

要求玩家属于社群，返回 `200 {"cursor":"opaque-cursor"}`。游标编码玩家、社群、已扫描事件序号，由类型化对象和标准库编码；不添加哈希或签名。取得游标之后加载现有查询，再建立事件流。

### 2.2 事件连接

`GET /api/communities/{community_id}/events?player_id=alice&cursor=opaque-cursor`

成功返回 `200 text/event-stream`。首次必须提供 cursor；自动重连可以通过 Last-Event-ID 提供，优先于查询参数。进入流之前检查范围与格式，非法游标 400、不可访问社群 404。有效但已过期的游标建立事件响应后发送 resync_required 并结束；客户端显式关闭原 EventSource，再重新同步。

事件 `id` 使用不透明恢复游标；`event` 使用下表类型；`data` 是一个 JSON 对象。已过滤的序号允许缺口。连接继续按当前位置查询，每页最多 100 条，无积压时等待提交通知；每 15 秒发送注释心跳。

| 事件类型 | data 内容与前端职责 | 接收范围 |
|---|---|---|
| conversation.message_created | community_id、conversation_id、message（现有 PlayerMessageView）；合并并按 message_id 去重 | 实际可见该消息的玩家 |
| conversation.turns_changed | community_id、conversation_id；重新查询当前可见轮次 | 可见相关来源或轮次的玩家 |
| conversation.summary_changed | community_id、conversation_id；刷新详情和会话列表 | 摘要确实受变化影响、并有读取资格的玩家 |
| conversation.members_changed | community_id、conversation_id；刷新成员及自身成员状态 | 有相关会话读取资格的玩家；退出者仍收到自身变化 |
| conversation.read_changed | community_id、conversation_id；刷新自身摘要与未读 | 阅读位置所属玩家 |
| community.status_changed | community_id；重新查询社群状态 | 社群玩家成员 |
| checkpoint | 空对象；只更新事件恢复位置 | 当前连接 |
| resync_required | reason=cursor_expired；关闭连接并执行初次同步 | 当前连接 |
| access_revoked | reason=membership_required；停止连接和原范围接入 | 当前连接 |

checkpoint 在扫描过滤记录后发送，业务事件已携带当前位置时不重复发送同位置确认。心跳没有 id。控制事件不写入持久业务事件表。成员资格丧失后不得持续接收业务事件。

summary_changed 覆盖新消息、成员、会话状态和未读变化；批量合并同事务同对象的相同通知。不可见消息不得导致其他玩家收到摘要通知。投影根据变化来源与原受众判断接收资格，不根据当前成员列表扩大消息受众。变化通知允许查询比事件发生时更新的当前状态。

## 3. 文件结构与职责

| 路径 | 实施内容 |
|---|---|
| shared/realtime.py | 事件写入端口、不可变事件引用与恢复位置类型 |
| infrastructure/realtime/repository.py | 同事务事件记录、分页扫描、高水位和清理边界 |
| infrastructure/realtime/broker.py | 线程安全、按社群通知代次管理订阅；连接不排队保存全部事件 |
| infrastructure/realtime/stream.py | 补充读取、在线等待、心跳、SSE 编码、发送超时和关闭 |
| infrastructure/realtime/retention.py | 每小时清理与持久边界更新 |
| app/realtime.py | 事件路由与应用级业务投影分派；沿用现有依赖注入和错误转换 |
| modules/conversations/services/events.py | 消息与会话通知的玩家投影，复用现有读取与共同观察规则 |
| modules/social/events.py | 轮次变化的可见性投影，复用 TurnQuery 的规则 |
| modules/communities/events.py | 社群运行状态事件的玩家投影 |
| infrastructure/database/sql/0011_realtime_events.sql | 新表、索引及清理边界；保留全部原业务数据与密钥 |
| app/composition.py、app/main.py、app/lifecycle.py | 构造和注入事件服务，注册路由，启动清理与关闭订阅 |
| infrastructure/database/connection.py | 可选提交后回调；在成功 commit 后执行，回滚不执行，保证提前 return 的事务仍能通知 |
| pyproject.toml、uv.lock | 增加 sse-starlette，使用 EventSourceResponse 完成标准 SSE 编码、心跳、断开检测与发送超时 |

表使用 `realtime_events` 保存单调事件序号、类型、社群、业务来源引用及 UTC 时间；`realtime_event_state` 保存清理边界。AUTOINCREMENT 保证清理后序号不复用，高水位从数据库序号状态读取。事件不复制 Thought 或整个任务结果。恢复扫描位置绑定玩家与社群，清理边界为全库事件序号。

固定运行参数：保留 24 小时、清理间隔 1 小时、心跳 15 秒、扫描批次 100、发送超时 30 秒。本轮采用有明确名称的集中常量，不增加功能开关或未使用配置。

传输复用 [sse-starlette 的正式实现](https://github.com/sysid/sse-starlette)，项目只实现事件选择、恢复与业务投影，不自行编写 SSE 格式解析器或连接发送框架。依赖版本通过实际 FastAPI、Starlette 和 Python 约束解析后写入锁定文件。

通知入口通过事件循环的线程安全调度完成唤醒。Database 的提交后回调只负责通知，不执行网络发送；通知服务关闭或异常不能改变已提交业务的成功语义。事件投影在短读取事务中完成，生成待发送数据后关闭事务。

## 4. 业务接入位置

1. `MessageIntake.send()`：新玩家消息记录 message_created 与受众限定的 summary_changed；原请求重试不新增事件。
2. `ConversationCommit.commit()`：审核通过的角色消息记录同类事件；沉默只改变轮次时记录 turns_changed；拒绝、取消和失败通过正式状态入口记录实际变化。
3. social 规划、生命周期与完成入口：轮次创建、执行状态、参与决定与接话链终态通知对应会话；事务内合并重复通知，不推送任务心跳和诊断明细。
4. `ConversationService`：创建、加入、退出及实际会话状态变更记录成员和摘要通知；管理写入口复用同一业务服务，因此同样产生通知。
5. `PlayerConversationQuery.mark_read()`：只有阅读位置实际前进时记录 read_changed 与该玩家的 summary_changed。
6. `CommunityService`：运行状态实际改变记录 status_changed；暂停不关闭事件连接，暂停结果与进行中任务后续状态仍可读取。

实现前沿调用链检查每个实际状态写入口，包括恢复、耗尽、插话取消和管理成员操作，避免只在 HTTP 路由发布事件。事件产生属于业务服务，Repository 不从底层 SQL 猜测业务变化。

## 5. 实施顺序与完成条件

| 顺序 | 工作 | 当前进度 | 完成条件 |
|---|---|---|---|
| 1 | 文档与契约最终确认 | 等待用户确认 | 确认范围、事件内容、恢复和保留规则 |
| 2 | 迁移、共同契约、事件存储、提交后通知 | 待实施 | 事务回滚、重复请求、清理和序号连续性通过真实 SQLite 验证 |
| 3 | 社群与聊天业务入口及玩家投影 | 待实施 | 所有相关正式变化可恢复，私有内容与离开期间消息被过滤 |
| 4 | SSE 路由、生命周期及断线恢复 | 待实施 | 真实网络连接即时收到事件，多个订阅者、断线与重启验证通过 |
| 5 | 正式参考、指南与状态同步 | 待实施 | 由真实应用生成 OpenAPI、数据库与源码参考，接入说明与实际协议一致 |
| 6 | 验收、清理临时文件 | 待实施 | 完成范围内检查、服务与临时资源清理，删除本文 |

## 6. 必须验证的行为

- 使用真实服务、SQLite 和 HTTP 事件连接；不使用 mock 或虚构生成结果。真实模型专项验证一条角色回应完成后通过 SSE 到达。
- 玩家消息、实际角色消息、轮次创建与完成、沉默、失败耗尽、玩家插话、成员变化、已读与社群暂停恢复均产生符合公开范围的事件。
- 两名订阅者分别收到相同可见变化；不同玩家私聊隔离，历史私有受众、离开再加入及原任务迟到回应保持现有规则。
- 已退出玩家收到自身退出通知，随后不能取得离开期间消息；更换玩家或社群的游标被拒绝。
- 获取初始位置之后、读取历史之前及建立 SSE 之前产生消息，均能补充；重复消息按编号识别。
- 扫描为空与新事务提交交错时仍被唤醒；空闲连接只等待和发送心跳，不循环查询消息数据库。
- 断线后 Last-Event-ID 补充成功；真实进程重启后事件仍可恢复；超期游标要求重新同步，未来游标拒绝；不可见记录通过 checkpoint 推进位置。
- 事务回滚不保存事件，幂等重试不产生新事件；提交成功后通知失败不改变业务确认，重新连接仍能读取事件。
- 慢连接发送超时释放订阅；客户端退出、服务关闭和清理任务退出不遗留连接与后台任务。
- 现有查询、模型任务和轮询客户端继续可用；迁移不改已有消息、记忆、任务、密钥和模型配置。

检查包括相关回归、真实网络事件验证、迁移、静态检查、安装包资源、文档链接及实际契约生成检查。不要运行前端构建、生成前端类型或修改前端文件。

## 7. 实现完成时的正式文档同步

- 新建 `reference/event-api.md`，记录实际连接路径、事件类型、字段、控制事件、恢复与错误，事件结构由后端类型定义生成并检查，避免手工参考与代码分别维护字段。
- `reference/http-api.md` 登记实际 SSE 与游标入口并链接事件参考；更新 OpenAPI 的 text/event-stream 响应说明。
- `guides/frontend-integration.md` 按首次读取、连接、缓存更新和恢复重写通信章节；保留消息发送、历史与已读规则，说明前端接入由前端分支实施。
- `guides/verification.md` 登记已执行证据；`status.md` 记录后端已交付与前端尚未接入的实际边界。
- 生成数据库参考与源码导航；只在新增实际配置时更新配置参考。本方案使用常量，因此不预先增加配置项。
- 更新后端 README 的实际契约与接入入口。正式设计保持长期规则，不复制本文件的阶段进度和修改清单。

验收完成后删除本文，不将单次实施过程放入 AGENTS.md 或历史总体方案。
