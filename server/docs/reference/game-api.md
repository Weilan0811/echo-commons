# 游戏 HTTP 接口

本文描述已实现的五子棋接口。逐字段类型见[OpenAPI](openapi.json)，规则与模块职责见[游戏契约](../../../docs/gameplay/游戏与角色活动接口.md)。请求沿用本地 `player_id` 身份选择方式，宿主检查真实社群资格和游戏参与记录。

## 1. 目录、房间与参与

| 方法与路径 | 请求要点 | 成功结果 |
|---|---|---|
| GET /api/game-types | 无参数 | 200，`items` 为实际注册玩法，当前只有五子棋 |
| GET /api/game-types/{game_type} | 玩法标识 | 200，显示名称、规则版本、人数与有类型配置 |
| GET /api/games | `player_id`、`community_id`；可选 `game_type`、`status`、`cursor`、`limit` | 200，`Page[GameSessionResponse]`（房间分页） |
| POST /api/games | `player_id`、`community_id`、`request_id`；游戏类型、规则、初始席位与配置 | 201，创建操作结果及局内会话 |
| GET /api/games/{game_id} | `player_id` | 200，房间概要、会话关联、本人参与历史与可用操作 |
| POST /api/games/{game_id}/participants | `player_id`、`request_id`、`expected_state_version`、`seat_id` | 200，本人实际加入结果 |
| POST /api/games/{game_id}/leave | 通用操作字段及 `participation_id` | 200，等待阶段的本人离开结果 |
| POST /api/games/{game_id}/start | 通用操作字段 | 200，创建者开始对局的结果 |
| POST /api/games/{game_id}/resign | 通用操作字段及 `participation_id` | 200，实际认输与结局 |
| POST /api/games/{game_id}/cancel | 通用操作字段及非空 `reason` | 200，取消结果，会话保留历史及结束入口 |
| POST /api/games/{game_id}/end | 通用操作字段及 `expected_conversation_version` | 200，必要时取消游戏，并归档会话 |
| GET /api/games/{game_id}/operations/{request_id} | `player_id` | 200，本人发起的原宿主操作结果 |

通用操作字段为 `player_id`、`request_id` 和 `expected_state_version`。创建使用全局创建请求范围；其他操作使用对局与操作者范围。原请求重试返回相同结果，版本已变化、本人已经离开或会话已经归档也能取得原确认。同一编号改变内容或操作种类返回冲突。

当前创建默认 `game_type=gomoku`、`ruleset_id=gomoku.freestyle`、`ruleset_version=1`、`initial_seat_id=black`、`config={}`，也可以明确提供这些字段。五子棋配置不接受额外字段。加入只操作本人，浏览器不能填写任意 `participant_ref` 或代表其他玩家；角色邀请尚未开放。

`GameSessionResponse`（房间读取结果）包含：

| 字段 | 含义 |
|---|---|
| `community_id` | 所属社群 |
| `game` | 五子棋概要：规则、状态、版本、配置、当前真实席位和结局 |
| `conversation` | 局内会话编号、状态及版本 |
| `self_participations` | 本人的实际参与区间，保留离开与重新加入的区别 |
| `self_participation_id` | 本人当前参与编号，没有当前席位时为空 |
| `capabilities` | 当前是否允许加入、离开、开始、认输、取消和结束 |

房间概要供所属社群成员读取，进入页面不自动加入。创建者先作为唯一成员等待第二人；开始后名单固定。等待房间没有已初始化棋盘，应读取概要。

`GameOperationResponse`（宿主操作结果）返回 `community_id`、`game_id`、`operation`、操作完成时的 `conversation`、实际变化的 `memberships` 及可空的 `game_receipt`。结束已结算或已取消游戏时，`game_receipt` 为空；结束未完成游戏时，引用实际取消回执。结算后可以赛后交流，取消后拒绝新消息，归档后保留只读历史。局内聊天继续使用[已有消息接口](http-api.md)。

## 2. 局势、动作与正式历史

| 方法与路径 | 请求要点 | 成功结果 |
|---|---|---|
| GET /api/games/{game_id}/view | `player_id` | 200，具体五子棋局势与本人的真实行动机会 |
| GET /api/games/{game_id}/decision-input | `player_id`、`opportunity_id` | 200，同一次读取中的局势、有效机会与规则说明 |
| POST /api/games/{game_id}/actions | `player_id`、`request_id`、`opportunity_id`、`expected_state_version`、`action` | 200，已提交动作回执 |
| GET /api/games/{game_id}/actions/{request_id} | `player_id`，可选本人的 `participation_id` | 200，本人原动作回执 |
| GET /api/games/{game_id}/events | `player_id`；可选 `cursor`、`limit`、本人的 `participation_id`、`through_state_version` | 200，可见正式事件及后续读取位置 |

落子动作使用 `{"type":"place_stone","x":7,"y":7}`，坐标为 0～14 的整数。颜色由真实席位确定。局势与行动机会在同一读取事务取得，客户端不自行推断轮到谁。动作成功一次只推进一次棋局版本，回执查询与原请求重试均复用原结果。

当前视图与决策输入要求真实当前参与资格。历史与动作回执可明确选择本人原参与区间，不能通过他人的编号取得历史。正式事件按发生时的实际受众过滤，后来占用同一席位不会继承他人的记录。

列表与事件分页复用共同游标工具。列表游标绑定玩家、社群、玩法和状态筛选；事件游标绑定玩家、对局、参与编号与可选版本上限。`limit` 默认 50，范围 1～200。经过不可见记录时，事件页可以为空但仍有后续位置。

列表结束时 `cursor` 为空；正式事件即使当前 `has_more=false`，仍返回可继续补充新事件的 `cursor`。离开后重新加入时，默认读取区间改变，旧游标不能直接用于新范围；明确选择本人原参与编号后可以继续原历史。`through_state_version` 限制历史读取的棋局版本上限，不能超出当前版本。

## 3. 实时同步与错误

游戏变化使用现有社群 SSE（服务器推送）连接的 `game.changed` 事件，内容仅为 `community_id`、`game_id` 和 `state_version`。所属社群成员可以据此刷新大厅和房间；棋盘、私人观察与正式历史分别经有资格的查询取得。事件格式、初次同步、断线补充及过期恢复见[事件接口](event-api.md)。

先取得 SSE 位置，再读取房间与聊天，最后从原位置连接。通知提示重新查询，不能当作完整局势或记忆来源。结束已结算活动不增加棋局版本，此时通知仍用于刷新房间与会话资格。正式事件游标和 SSE 游标分别保存，24 小时通知保留期不限制正式棋谱历史。

| HTTP 状态 | 典型情况 |
|---|---|
| 400 | `illegal_action`（动作规则不允许）、`invalid_seat`（席位无效）、`invalid_cursor`（游标格式或范围不符） |
| 403 | `operation_forbidden`（有读取范围，但没有执行操作的资格） |
| 404 | 对局不存在、不属于社群、没有所需参与资格或本人范围中不存在回执 |
| 409 | `state_version_conflict`、`opportunity_expired`、`not_current_actor`、`idempotency_conflict`，以及尚未开始、已经开始或已经结束等状态冲突 |
| 422 | 缺少请求字段、非法坐标或动作类型、尝试提供未开放字段 |

字段错误由请求校验返回，业务错误沿用统一的 `error.code` 与 `error.message` 结构。状态冲突后重新读取局势与机会；需要改变操作内容时使用新的请求编号。
