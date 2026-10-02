# 多人交流示例

在 `server/` 运行 `uv run echo-commons init --example`，通过正式业务服务创建两名玩家、两个小槿角色实例及群聊。原始数据随包保存在 `resources/examples/group.json`。重复执行同一示例会复用相同业务对象。

启动 `uv run echo-commons serve` 后，在 `/docs` 调用 `POST /api/conversations/example-conversation/messages`：

```json
{
  "player_id": "example-alice",
  "client_message_id": "greeting-001",
  "text": "两位小槿，请各自说说今天想一起做什么。"
}
```

随后使用 `player_id=example-alice` 查询该会话的 `/messages` 和 `/turns`。安静窗口结束后，后台执行器为两个角色建立独立任务，调用已配置的真实模型并提交回应。每个角色拥有自己的状态、记忆和执行记录。

私有消息可以设置 `visibility=recipients`，并明确传入 `recipients`，例如 `[{"kind":"character","actor_id":"example-jin-one"}]`。系统保存真实受众；另一名玩家与另一个角色无法读取该消息。

为第二个社群准备另一份 JSON：使用不同的社群、会话和角色实例标识，再执行 `echo-commons init --example <文件路径>`。这份示例没有任何默认世界配置，所有标识只属于明确初始化的数据。
