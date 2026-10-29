# 玩法分析与外部分析器

更新日期：2026-10-28。已实现五子棋候选分析、只读规则预览和 Rapfi 进程管理；角色任务、模型选择、冻结输入保存及正式行动由后续 Activity 单元接入。

## 1. 职责与扩展位置

`modules/activities/gameplay/contracts.py` 定义玩法分析接口。`GameplayRegistry` 按游戏类型、规则及其版本选择实现，调用方传入角色实际可见的 `GameView` 和其中的行动机会。实现返回同一格式的候选、规则事实、分析估计和资源记录。

当前 `GomokuAnalyzer` 调用 Rapfi，将原始分值和走法转换为共同结果。Rapfi 的协议、权重、进程和配置在 `infrastructure/game_analysis/rapfi/` 中维护，基础设施不导入 Activity。

飞行棋、Kingdomino 分别增加自己的玩法分析实现并注册。直接计算可以使用游戏公开能力；其他外部分析器在基础设施中增加自己的子目录。共同接口不要求搜索深度、子进程或统一胜率。候选的正式动作类型通过泛型保留，结果可以按该动作类型完整序列化和恢复。

## 2. 正式调用

```python
from echo_commons.modules.activities.gameplay.contracts import AnalysisRequest

observed = application.game_observations.observe(community_id, character_id, game_id)
analysis = await application.game_analysis.analyze(
    AnalysisRequest(
        view=observed.view,
        opportunity=observed.view.opportunities[0],
    )
)
```

调用前应确认角色有当前行动机会。分析只读取传入的公开观察，不读取游戏表，不执行动作。`suggested_actions` 接收已经转换为正式动作的合法建议；复杂聊天含义由后续角色判断负责。

注册入口检查观察中的真实机会、参与区间、席位和状态版本。`GameplayAnalysis` 保存游戏与规则身份、观察版本、参与区间、机会、合法动作总数、候选及分析资源。`recommended_candidate_id` 是引擎对照动作，正式动作继续由角色决定。候选数量较少不改变 `legal_action_count` 和 `choice_required`。

4.1 尚未创建持久活动任务。调用结果作为完整值返回；后续冻结输入直接保存这份结果，两种模型路径使用同一份候选依据。

## 3. 五子棋候选与事实

游戏包通过公开的 `read_gomoku_tactics(view)` 与 `preview_gomoku_actions(view, actions)` 提供只读分析。它们复用五子棋落子与连线判断，支持自由规则版本 1，不保存预览产生的状态。

候选优先保留当前直接获胜位置、对手直接获胜位置的封堵、调用方提供的合法建议和引擎首选，再加入多候选搜索结果。需要保留的候选超过配置容量时明确报告 `candidate_budget_exceeded`，调用方可以调整预算；非法建议报告 `illegal_suggestion`。

每个候选分别保存：

- `facts`：游戏规则确定的直接胜负、落子后的对手立即获胜位置、己方下一次落子可获胜的位置和封堵位置。己方后续威胁仍会受到对手下一步影响。
- `estimates`：实际取得的 Rapfi 原始分值、搜索深度、节点及后续走法。分值尺度为 `rapfi.raw`，不换算成真实对局胜率；搜索线表示估计，未取得估计时保持空集合。
- `origins`：规则战术、正式建议或引擎候选来源。同一动作只展示一次。

明确建议不在初次搜索结果中时，可以通过限定根候选补充真实分析。默认总搜索预算 500 毫秒，有建议时先分配四分之三用于普通搜索，剩余用于缺失建议；没有缺失建议时不追加请求。各次调用分别记录实际预算与耗时。

## 4. 固定资源与安装

固定官方发布版 `250615`，引擎版本 `0.43.01`，自由规则权重 `mix9svqfreestyle_bsmix.bin.lz4`；配置和基础模型来自同一发布包。资源来源见随包的 `resources/game_analysis/rapfi.toml`、[官方发布](https://github.com/dotb1ue/rapfi/releases/tag/250615)和[对应协议源码](https://github.com/dotb1ue/rapfi/blob/250615/Rapfi/command/gomocup.cpp)。

在 `server/` 执行：

```powershell
uv sync
uv run python tools/install_rapfi.py
```

默认读取 `config/settings.toml`；`--settings` 可指定其他设置文件，`--archive` 可使用已下载的同版官方 7z 发布包。安装使用 `py7zr` 读取归档，保留配置、配套模型、作者名单及官方许可，并记录安装来源。已完成的同版安装可直接复用；已有非空目录且没有完整安装记录时不覆盖其中内容。

默认程序根据系统选择发布包中的 Windows/Linux SSE 版本或 macOS Apple Silicon 版本。指定其他发布程序时，先设置 `game_analysis.rapfi.executable` 再安装。实际验证平台及限制见[后端状态](../status.md)。程序和权重保存在运行资源目录，Python 安装包包含版本说明与代码。

## 5. 协议、资源与恢复

引擎在第一次分析时启动，应用拥有并在关闭时回收。没有分析请求时不启动进程。单个实例通过异步锁串行处理观察，避免不同棋局的协议输入混合；应用的其他业务仍可运行。

使用 `ABOUT` 检查版本、`START` 初始化棋盘、`INFO rule 0` 采用自由规则、`YXBOARD` 载入按真实先后顺序排列的棋子、`YXNBEST` 获取多候选。棋子协议身份按当前角色转换，坐标保持从零开始的 `(x, y)`。`INFO PV … DONE` 的完整记录提供每条候选搜索线，最终坐标提供引擎首选。各候选保留自身实际达到的深度，不假定全部完成同一搜索深度。

每次分析重置棋盘、根候选限制和搜索时间。后台思考关闭，引擎自身对局数据库关闭；运行配置必须保持原生坐标和 `mix9svq` 评估器。线程数和散列表内存分别受配置控制，散列表预算不表示整个进程的内存上限。

请求期限覆盖进程准备和当前协议调用。超时、取消或协议失败会回收进程；后续请求可按原观察重新启动。玩法注册入口仅对进程退出、期限耗尽和运行故障按 `task.max_agent_attempts` 有限重试，并在成功结果或最终异常中保留失败代码。未安装、规则不支持、候选预算和非法建议等问题直接返回，不使用其他策略替代搜索结果。

## 6. 验证入口

`tests/infrastructure/test_game_analysis.py` 使用真实游戏服务、SQLite 和 Rapfi，验证正常候选、规则预览、边界与长连、正式建议、序列化、进程复用、取消、期限、恢复和应用关闭。没有安装引擎时，相关用例明确显示跳过，并给出安装命令。

`tools/verify_games_installed.py --rapfi-directory <实际资源目录>` 在源码目录外验证安装包、HTTP、SSE、只读候选分析及进程回收。验证不执行角色模型调用；角色实际选择、聊天输入和两种模型路径的内容验收在后续 Activity 单元完成。
