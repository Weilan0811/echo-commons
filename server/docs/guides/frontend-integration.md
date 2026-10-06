# 前端接入步骤

## 1. 身份、社群与会话

自定义人物先读取 `/api/character-authoring/template`，展示基础引导、默认十五题与固定背景提醒。基础、故事、采访分别提供 AI 辅助按钮，校准按钮只整理三份人设文档；按后端 workflow 显示阶段确认和复核状态。完整路径与字段见 [创作接口](../reference/http-api.md#6-自定义人物创作)。

创建只需名字和简短描述，默认生成可编辑的三份基础正文；作者也可以直接填写正文。确认基础后可以结束，或者填写并确认故事。完成故事后先审核正文，再选十至十五道采访题，回答可为空，每次选择一至五题生成。首批建立采访依据，后续批次沿用同一人设；接受回答后文档待审核，不阻止继续采访。全部回答完成后确认采访，再校准并审核三份正文。作者可以手工完成材料和正文审核，无需模型调用。

AI 候选未接受前不改作者材料。预览本操作的正文、修改说明与来源，接受时调用独立 `/candidates/{candidate_id}/accept`；继续手工编辑则通过 PUT 保存完整 content。接受不自动确认阶段，校准接受可以直接审核三份文档。存在冲突时展示出处，由作者决定材料与正文，再生成或手工审核。采访详略由角色与情境决定，界面不要求固定回答字数。

每次写入保留 expected_revision；候选请求保留原 candidate_id，失败后重新生成使用新编号。修改前面设定时保留后续原文并提示复核，按阶段顺序再次确认。未完成采访可以明确删除整份材料，在故事阶段结束。仅改头像不影响阶段，改名要求文档审核。

最终确认页面展示固定背景提醒并发送 acknowledge_fixed_background=true。固定资源从 `/api/custom-blueprints` 选择，沿用角色实例创建和会话入口；预置模板列表保持原行为。material_processing=stored_only 表示作者原文保存完成，初始记忆消化尚未实现。固定后可以复制为新草稿，复制保留文字并要求重新确认，当前没有重置旧实例入口。

## 2. 打开最新消息、向上翻页与轮询

首次读取 `.../messages/history?player_id=alice`，展示返回 messages，保存 older_cursor 和 poll_cursor。向上滚动只使用 older_cursor；返回的后续历史页 poll_cursor 为空，不覆盖增量位置。新消息使用 `.../messages?player_id=alice&cursor=...`，接续首次 poll_cursor。

增量 has_more=true 时立即继续下一页，过滤后的空页仍可有下一页；没有新消息时保留返回 cursor 等待。历史 has_older=false 时结束向上翻页。对象列表的 items、cursor、has_more 使用独立协议与查询缓存。

所有消息按 message_id 去重。切换玩家或会话时清除对应游标和身份缓存。历史私有消息与成员离开期间的消息不会要求前端补齐每个序号；单条读取和 reply_preview 用于引用展示，不可见引用不补读管理正文。

## 3. 发送、轮次与已读

新输入生成 client_message_id，网络重试保留原标识与原字段。202 表示接受完成，角色在后台执行。发送正文不包含 visibility 或 recipients；新消息对发送时的会话成员可见。需要私聊时创建玩家与角色的 direct 会话，需要与部分成员交流时创建包含这些成员的 group 会话。mentions 表示提及，reply_to_message_id 引用自身可见消息。一次角色发言是完整消息，页面可以按展示需要分气泡。

轮次的 input_message_ids 对应当前发送来源，参与状态区分等待、完成、沉默和失败。后台失败不自动重新发送已接受的玩家消息。

会话概要直接提供最后预览、未读及当前成员状态。玩家实际查看消息后提交 `PUT .../read`，正文是 player_id、through_message_id。读取和轮询不提交已读；空历史无需提交。服务器处理两个标签页的较旧位置。

## 4. 成员操作与冲突

自身重新加入使用 `PUT .../membership`，正文提供 player_id、client_operation_id。自身退出使用 DELETE 同路径，查询提供 player_id、expected_membership_id、client_operation_id。首次参加由创建或管理加入建立。

网络重试保持同一操作编号及内容。返回原结果后，如需当前成员状态重新读取会话详情。成员版本或区间冲突时保留输入并刷新状态；内容冲突不能自动更换编号重试。离开期间的消息不会因重新加入变为可见。

400 检查输入或重新读取第一页；404 停止展示不可读取对象；422 展示字段错误；409 使用具体错误码；503 依据现有请求策略处理。完整路径与字段见 [HTTP 参考](../reference/http-api.md)。

## 5. 管理与缓存

管理端使用 `/internal/communities/{community_id}/characters` 和 `.../conversations` 的独立完整列表。通用成员操作只在管理路径，必须提交 expected_membership_version 与 client_operation_id。私人消息、冻结上下文、记忆和恢复诊断使用 [管理参考](../reference/management-api.md)，保持独立查询缓存。

当前使用 HTTP 轮询，没有新增实时推送或流式发言接口。跨域开发设置 server.cors_origins，服务保持既有监听配置。
