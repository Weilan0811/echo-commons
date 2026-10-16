# 本地开发与安装

## 准备和初始化

使用 Python 3.11—3.13 和 uv，在 server 目录执行：

源码目录需要同时包含同级 `games/`。宿主通过 `pyproject.toml` 的本地可编辑依赖加载游戏包；启动方式继续使用下面的正式命令。独立游戏规则与存储检查见 [游戏包说明](../../../games/README.md)。

```powershell
uv sync
uv run echo-commons init
uv run echo-commons inspect
```

init 建立新路径的空库，默认不创建社群或人物；inspect 只读显示结构版本、对象数量和配置状态。数据库不存在时只读命令失败，不替你创建。正式设置已在 config 目录，不运行 configure 覆盖它。

## 多人示例与服务

在 config/model-secrets.toml 按 [配置参考](../reference/configuration.md) 填入实际 credentials，然后执行：

```powershell
uv run echo-commons init --example
uv run echo-commons serve
```

示例创建 example-community、example-conversation、example-alice、example-bob、example-jin-one、example-jin-two；两位小槿使用同一模板但状态和记忆独立。重复示例通过正式对象身份处理。服务默认地址为 http://127.0.0.1:8765，打开 `/docs` 使用接口。

自定义示例采用包内 [group.json](../../src/echo_commons/resources/examples/group.json) 的完整格式，改用自己的标识，再执行 `uv run echo-commons init --example <JSON路径>`。不要把示例身份当成全局默认玩家。

公共和私有交流见 [多人示例](../../examples/README.md) 与 [前端接入](frontend-integration.md)。玩家窗口到期后后台规划回应，角色调用真实模型；模型未配置不会产生替代回复。

## 检查与导出

```powershell
uv run echo-commons --settings config/settings.toml inspect
uv run echo-commons export --output data/exports/community.sqlite3
```

全局 --settings 放在子命令前。export 保存一致的完整数据库副本，包含私有信息，目标存在时拒绝覆盖。不要删除原实验库或密钥来初始化新基线。

## 安装包

```powershell
uv build --project ../games --out-dir data/packages
uv build
uv venv <源码目录外的虚拟环境路径>
uv pip install --python <该环境中的python路径> data/packages/echo_games-0.1.0-py3-none-any.whl dist/echo_commons_server-0.1.0-py3-none-any.whl
```

在独立工作目录使用安装后的命令：

```powershell
echo-commons configure
echo-commons init --example
echo-commons inspect
echo-commons serve
```

configure 复制包内非秘密配置，已有文件时拒绝覆盖；密钥另外填写。SQL、人物五份资源、共同契约、配置模板和示例随包加载。工作目录外验证脚本为 [verify_installed.py](../../tools/verify_installed.py)，执行方式先查看 `--help`；它使用真实模型。

通信专项使用 [verify_realtime_installed.py](../../tools/verify_realtime_installed.py)。在源码目录外，使用安装后的 Python 执行 `python <脚本绝对路径> --settings <设置绝对路径>`；环境需安装 `httpx-sse`。脚本通过真实网络验证数据库迁移、消息推送与连接关闭，使用临时数据库，关闭模型任务。

游戏独立安装验证使用 [games/tools/verify_installed.py](../../../games/tools/verify_installed.py)，运行环境只安装游戏 wheel 及依赖；宿主与游戏共同安装验证使用 [verify_games_installed.py](../../tools/verify_games_installed.py)，另需安装开发验证依赖 `httpx-sse`。均在源码目录外执行脚本绝对路径，使用临时数据库，无需模型凭据。共同验证会启动并正常关闭真实 HTTP/SSE 服务，完成真人参与、聊天及九步获胜，确认安装包中的接口和 SQL 可用。需要复现锁定依赖时，先用 `uv export --frozen --no-emit-local --no-hashes` 导出，再作为安装约束。

## 验证及退出

快速检查和真实模型验证分开运行，见 [验证指南](verification.md)。结束服务使用正常终止，让生命周期停止 Workers 并关闭客户端。检查本轮启动的子进程，不结束其他任务的进程；临时数据库、构建和环境在不再需要时清理。
