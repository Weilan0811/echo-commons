# 前端接入步骤

## 1. 身份、社群与会话

自定义人物先读取 `/api/character-authoring/template`，展示基础引导、默认十五题与固定背景提醒。基础、故事、采访分别提供 AI 辅助按钮，校准按钮只整理三份人设文档；按后端 workflow 显示阶段确认和复核状态。完整路径与字段见 [创作接口](../reference/http-api.md#6-自定义人物创作)。

创建只需名字和简短描述，默认生成可编辑的三份基础正文；作者也可以直接填写正文。确认基础后可以结束，或者填写并确认故事。完成故事后先审核正文，再选十至十五道采访题，回答可为空，每次选择一至五题生成。首批建立采访依据，后续批次沿用同一人设；接受回答后文档待审核，不阻止继续采访。全部回答完成后确认采访，再校准并审核三份正文。作者可以手工完成材料和正文审核，无需模型调用。

AI 候选未接受前不改作者材料。预览本操作的正文、修改说明与来源，接受时调用独立 `/candidates/{candidate_id}/accept`；继续手工编辑则通过 PUT 保存完整 content。接受不自动确认阶段，校准接受可以直接审核三份文档。存在冲突时展示出处，由作者决定材料与正文，再生成或手工审核。采访详略由角色与情境决定，界面不要求固定回答字数。

每次写入保留 expected_revision；候选请求保留原 candidate_id，失败后重新生成使用新编号。修改前面设定时保留后续原文并提示复核，按阶段顺序再次确认。未完成采访可以明确删除整份材料，在故事阶段结束。仅改头像不影响阶段，改名要求文档审核。

最终确认页面展示固定背景提醒并发送 acknowledge_fixed_background=true。固定资源从 `/api/custom-blueprints` 选择，沿用角色实例创建和会话入口；预置模板列表保持原行为。material_processing=stored_only 表示固定人物资源保存作者原文；实例创建时再按 memory_mode 初始化。默认 simple 完成分块和全文索引，full 进一步完成长期整理与核心记忆。前端按 memory_status 展示 preparing、ready 或 failed；仅 ready 可加入聊天，failed 可调用准备重试接口。向量索引不影响准备完成。固定后可以复制为新草稿，复制保留文字并要求重新确认，当前没有重置旧实例入口。

## 2. 初次同步、事件与历史

先读取 `/api/communities/{community_id}/events/cursor?player_id=alice`，保存事件游标 C；再读取会话列表、选定会话最新历史、轮次和社群状态。首次历史响应中的 older_cursor 用于向上翻页，poll_cursor 用于原消息增量读取。它们与事件游标分别保存。

随后以 C 建立 `/api/communities/{community_id}/events?player_id=alice&cursor=...` 的 EventSource（浏览器事件连接），游标值通过 URL 参数编码。同一玩家与社群复用一条连接，监听具名事件；事件类型及完整结构见 [事件接口参考](../reference/event-api.md)。正常在线接收消息与状态事件，无需按固定间隔查询这些对象。

message_created 携带完整 message，按 message_id 合并。turns_changed 重新查询对应轮次，summary_changed 刷新会话详情和列表，members_changed 刷新成员与自身状态，read_changed 刷新当前玩家摘要，status_changed 刷新社群状态。同一对象的连续刷新合并安排，避免较旧查询覆盖较新结果。离开后成员名单接口不可读取时，清除当前名单展示并保留历史消息。

自动重连沿用最后收到的 SSE id。checkpoint 仅推进事件位置；resync_required 要求关闭连接，重新取得位置并加载当前数据。需要补充全部聊天消息时使用原 poll_cursor 分页读取：has_more=true 立即继续，过滤后的空页仍可能有后续；无新消息保留返回游标。历史 has_older=false 时结束向上翻页，后续历史页的空 poll_cursor 不覆盖原增量位置。

切换会话只更换对应查询与展示缓存，继续使用社群连接；切换玩家或社群时关闭原连接并清除身份范围相关缓存。页面退出关闭连接。历史私有消息与离开期间消息允许序号缺口；不可见引用不补读管理正文。后端交付与客户端接入进度分别见状态文档，不以此指南推断前端已经完成接入。

## 3. 发送、轮次与已读

新输入生成 client_message_id，网络重试保留原标识与原字段。202 表示接受完成，角色在后台执行。发送正文不包含 visibility 或 recipients；新消息对发送时的会话成员可见。需要私聊时创建玩家与角色的 direct 会话，需要与部分成员交流时创建包含这些成员的 group 会话。mentions 表示提及，reply_to_message_id 引用自身可见消息。一次角色发言是完整消息，页面可以按展示需要分气泡。

轮次的 input_message_ids 对应当前触发来源。群聊使用 chain_id 关联连续回应，parent_turn_id 与 depth 表达前后顺序；单个 status=completed 仍可能继续接话，应同时读取 chain_status。completed 或 cancelled 表示该链结束，chain_stop_reason 说明原因。chain_id 为空的私聊及旧轮次使用原 status。等待候选尚未进入 participation；只有实际安排或排除后才出现对应决定。后台失败不自动重新发送已接受的玩家消息。

会话概要直接提供最后预览、未读及当前成员状态。玩家实际查看消息后提交 `PUT .../read`，正文是 player_id、through_message_id。读取和轮询不提交已读；空历史无需提交。服务器处理两个标签页的较旧位置。

## 4. 成员操作与冲突

自身重新加入使用 `PUT .../membership`，正文提供 player_id、client_operation_id。自身退出使用 DELETE 同路径，查询提供 player_id、expected_membership_id、client_operation_id。首次参加由创建或管理加入建立。

网络重试保持同一操作编号及内容。返回原结果后，如需当前成员状态重新读取会话详情。成员版本或区间冲突时保留输入并刷新状态；内容冲突不能自动更换编号重试。离开期间的消息不会因重新加入变为可见。

400 检查输入或重新读取第一页；404 停止展示不可读取对象；422 展示字段错误；409 使用具体错误码；503 依据现有请求策略处理。完整路径与字段见 [HTTP 参考](../reference/http-api.md)。

## 5. 管理与缓存

管理端使用 `/internal/communities/{community_id}/characters` 和 `.../conversations` 的独立完整列表。通用成员操作只在管理路径，必须提交 expected_membership_version 与 client_operation_id。私人消息、冻结上下文、记忆和恢复诊断使用 [管理参考](../reference/management-api.md)，保持独立查询缓存。

管理查询继续使用其 HTTP 接口。跨域开发设置 server.cors_origins，服务允许 Last-Event-ID 请求头。代理应及时传递 text/event-stream，避免缓存或积累整个响应；关闭连接不会结束后台任务。角色消息完整保存后发送，当前没有逐字输出接口。

## 图像资产与展示

当前前端提供角色插画生成、头像裁剪与资产选择，以及官方社群封面选择。图片上传、社群封面生成和聊天背景生成已有后端接口，尚未提供前端入口。

官方预设图片与场景清单放在 frontend/public/assets/，不上传后端。社群创建或修改封面提交 cover_kind=preset 与稳定 cover_ref；用户封面选择 cover_kind=asset。封面修改使用社群 state_version，角色头像覆盖使用 appearance_version；版本过期时重新读取对象。

用户图片通过 `/api/assets/images` 上传。角色用途为 character_illustration，上传与生成都先取得完整插画。使用返回的 standard 地址显示裁剪框，建议上部正方形，边长为实际宽高较小值；移动或缩放后把坐标换算为实际图片像素，提交 avatar-crops 接口。确认取景得到 character_avatar 资产后，写入草稿 avatar_asset_id 或实例覆盖。显示时读取公共 avatar_url 和 illustration_url。官方角色直接使用随包的插画与预先裁好的头像。

生成前查询 generation-styles，提交用途、风格、描述与 scene_context；场景清单给出时间、光照、色彩和环境，公共提示只负责构图及画面要求。角色可引用所属草稿的 draft_id 与 revision，加上 appearance；后端不会读取私人运行记录。封面描述具体世界，聊天背景描述独立中性环境。

申请成功后短期查询 image-generations/{generation_id}，completed 时显示资产，failed 时显示操作提示并停止查询。内部错误类型通过管理接口查询，公开响应不包含这些字段。网络重试保留 client_request_id 和原输入；改变输入使用新编号。生成规格由用途固定，角色 1080×1350、封面 1600×600、背景 1920×1080，背景为单张横图，手机使用中心裁切。images 返回实际尺寸、标准图和档位地址，上传小图可能小于目标。

生成或上传完成只创建资产，作者明确选择后才修改业务引用。更换图片保留旧资产，可以再次选用或通过删除接口回收；先删除派生头像再删除来源插画。收到 community.appearance_changed 或 character.appearance_changed 后刷新对应公共对象，角色展示缓存同时更新头像和插画。接口和响应字段见 [HTTP 参考](../reference/http-api.md#7-图像资产与生成)。
