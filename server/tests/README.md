# 后端测试

在 `server/` 目录执行：

```powershell
uv run pytest
```

默认跳过 `model` 标记，使用真实 SQLite、业务服务、HTTP 和本地进程验证规则，不调用模型供应商。

`test_game_analysis.py` 的引擎用例读取正式 `game_analysis.rapfi` 配置。先执行 `uv run python tools/install_rapfi.py` 安装固定 Rapfi，再执行专项测试；未安装时明确跳过需要该程序的用例。规则预览测试仍使用真实游戏服务运行。分析器验证不调用角色模型。

## 目录职责

| 目录 | 内容 |
|---|---|
| `infrastructure/` | 按业务主题组织的测试及子进程启动脚本 |
| `support/` | 复用的社群、消息、队列、人物和记忆准备函数，以及捕获文件检查 |
| `fixtures/migrations/` | 固定的历史数据库输入记录，供真实迁移使用 |

公共准备函数从 `support` 导入。仅由一个测试文件使用的准备函数和 pytest fixture（测试准备函数）保留在该文件。公共代码调用正式服务或建立明确的历史输入，不返回预设的业务执行结果。

## 选择检查范围

修改一个模块时，运行对应主题文件；涉及公共契约、数据库或跨模块流程时，再运行完整免费检查。场景与文件的对应关系见[验证指南](../docs/guides/verification.md)。

```powershell
uv run pytest tests/infrastructure/test_memory_records.py
uv run ruff check tests
```

模型测试需要明确选择，会使用配置中的真实供应商并产生费用：

```powershell
uv run pytest -m model tests/infrastructure/test_character_experiences_model.py
```

只查看付费用例名单：

```powershell
uv run pytest --collect-only -m model
```

跨场景摘要、连续压缩、长期整理和回应的综合模型流程由 `test_character_experiences_model.py` 负责；双角色私有材料的模型隔离与重复提交由 `test_reflection_execution.py` 负责。针对其他能力，只选择相应模型用例，避免重复执行大型流程。

提示测试检查实际资源装入、材料选择和权限范围。提示正文与规划文档之间的逐字比较属于修改时的交付核查，不作为长期业务测试。
