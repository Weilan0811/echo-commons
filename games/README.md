# 独立游戏包

`echo_games` 负责游戏规则、对局、席位、参与历史、行动机会、回执和正式事件。当前实现 `gomoku.freestyle` 版本 1：15×15 自由五子棋。包只依赖 Pydantic 和 Python 标准库，不导入 `echo_commons`。

在 `games/` 下运行：

```powershell
uv sync
uv run pytest
uv run ruff check .
uv run mypy
uv build
```

宿主仍在 `server/` 下执行 `uv sync` 和 `uv run echo-commons serve`，通过本地可编辑依赖加载本包。安装发布包时需要同时安装游戏包与宿主包。

## 公开入口与事务

业务类型、规则注册和 `GameService` 从 `echo_games.public` 导入。首次建表使用 `echo_games.schema.create_schema`，函数只执行正式 SQL，不管理迁移版本；宿主由全局迁移 21 调用它。

所有服务操作要求调用者开启事务，数据库连接可以使用标准 `sqlite3.Connection`，无需宿主连接类。读取使用同一事务，保证局势和行动机会属于同一个版本。写入由调用者统一提交或回滚，服务不嵌套开启事务。

```python
import sqlite3

from echo_games.public import GameService, GomokuCreateGameCommand, default_registry
from echo_games.schema import create_schema

connection = sqlite3.connect(":memory:", isolation_level=None)
connection.execute("PRAGMA foreign_keys=ON")
connection.execute("BEGIN IMMEDIATE")
create_schema(connection)
service = GameService(default_registry())
receipt = service.create_game(
    connection,
    "player:alice",
    GomokuCreateGameCommand(request_id="create-1"),
)
connection.commit()
connection.close()
```

`request_id` 表示一次操作。相同请求重试返回原回执；编号相同但内容不同会被拒绝。`expected_state_version` 表示作出选择时的棋局版本，防止依据旧局势提交新动作。`SeatAccess` 必须由宿主根据真实身份及参与记录构造。

`GameReadAccess` 与 `GameListQuery.game_ids` 由宿主先检查社群读取资格；游戏不读取社群表。私人观察、事件和动作回执进一步按真实参与区间检查。创建者代表其他主体操作前，宿主必须检查它是否是获准邀请的角色。

宿主可以注入 `GameChangeRecorder`，通过 `record_changed(connection, game_id, state_version, event_ids)` 在当前事务登记变化通知。独立游戏运行不需要通知服务；网络发送由宿主在提交之后执行。

正式测试数据清理使用 `GameCleanup` 统计和删除指定对局，仍由调用者控制事务。宿主先按社群关联确定范围，再移除所属关联和游戏记录，保留其他对局。

## 公共模型与具体玩法

`Game[ConfigT, StateT]` 表示共同对局结构，两个类型参数分别指定配置与完整内部局势。`GameStatus` 继续统一表达等待、进行、结算和取消。公共模型、规则协议、注册表、存储和服务均不导入具体玩法。

观察、动作、动作结果、终局结果和正式事件分别具有自己的类型参数。规则通过 `GameDefinition` 提供初始化、观察、合法动作、执行、认输和 `outcome`（终局结果读取）。`RuleTransition` 一次返回新内部局势、动作回执结果和实际规则事件；公共服务根据 `outcome` 决定是否结束，不要求所有玩法的内部局势都有 `result` 字段。

五子棋在 `gomoku/contracts.py` 中将公共结构具体化，例如：

```python
GomokuGame = Game[GomokuConfig, GomokuState]
GomokuSubmitActionCommand = SubmitActionCommand[PlaceStoneAction]
GomokuView = GameView[GomokuState, PlaceStoneAction]
```

同一个公共结构因此能使用不同玩法的数据类型。这里的内部局势和观察是两个独立类型参数；五子棋全部棋盘公开，两者暂时使用同一个 `GomokuState`。其他玩法可以返回自己的可见观察模型。

每种规则携带一份 `GameModels`，登记具体对局、请求、视图、回执和事件模型。`composition.py` 显式注册实际规则。数据库回读先根据保存的 `game_type`、`ruleset_id` 和 `ruleset_version` 查注册表，再用对应模型解析；未安装原规则时明确拒绝读取，不套用其他玩法。

公共创建命令要求明确提供玩法、规则版本、席位和配置，五子棋的默认值由 `GomokuCreateGameCommand` 提供。服务入口使用注册模型验证请求，再按具体模型保存与返回数据。目录和列表可能同时容纳多种模型，使用 `SerializeAsAny` 保留已验证实例的具体字段；这是 Pydantic 支持的[按实际类型序列化](https://docs.pydantic.dev/latest/concepts/serialization/#serializing-with-duck-typing)方式。

以后增加玩法时，在所属目录定义模型、规则与具体公共类型，登记 `GameModels` 并在组合入口注册。公开 HTTP 类型在宿主接口接入时组合实际已实现的玩法，公共领域与存储不维护具体玩法类型清单。

## 当前交付范围

游戏包已实现内部生命周期、五子棋操作和持久化。宿主的 `GameParticipationService` 协调真人席位、局内会话和原请求重试，另提供[游戏 HTTP 接口与通知](../server/docs/reference/game-api.md)；游戏包继续独立于社群与聊天。玩家页面和角色执行尚未接入，实施安排见[游戏开发计划](../docs/05-gameplay-foundation-implementation-plan.md)。

完整目标接口见 [游戏契约](../docs/gameplay/游戏与角色活动接口.md)，后续按新增玩法扩展明确的状态、动作与结果类型，不用任意字典代替业务类型。
