# HTTP 接口参考

## 1. 共同规则

本文描述当前实际公开接口。逐字段类型、枚举和可空字段见从应用生成的 [OpenAPI](openapi.json)，长期规则见 [玩家 API 设计](../design/player-api.md)。SSE 的事件与恢复协议见 [事件接口参考](event-api.md)。请求正文拒绝未知字段，时间使用带时区 ISO 8601，正式保存为 UTC。

当前为本地测试模式，`player_id` 表示选择的玩家，没有账户认证。ActorRef 为 `{"kind":"player","actor_id":"alice"}`，kind 是 player 或 character；系统消息使用独立 system 来源。公共展示包含 actor、display_name、avatar_url、illustration_url；角色展示绑定实际模板版本。

对象列表返回 items、cursor、has_more，默认 limit=50，范围 1—200；结束时 cursor=null。游标绑定查询种类、玩家与筛选范围。对象不存在或读取范围不符返回 404，存在范围的空列表返回 200。

## 2. 全部公开接口

| 方法与路径 | 请求字段或查询 | 成功响应 |
|---|---|---|
| POST /api/players | display_name 必填；player_id 可选 | 201 PlayerView |
| GET /api/players | 对象列表分页 | 200 Page[PlayerView] |
| GET /api/players/{player_id} | 路径身份 | 200 PlayerView |
| POST /api/communities | player_id、name 必填；timezone 默认 UTC；community_id、world_time_utc、cover_kind、cover_ref 可选 | 201 PublicCommunityView，默认 paused，发起者同时加入 |
| PATCH /api/communities/{community_id}/appearance | player_id、expected_version、cover_kind、cover_ref；两个封面字段同时为空表示清除 | 200 PublicCommunityView；检查社群状态版本 |
| PATCH /api/communities/{community_id}/characters/{character_id}/appearance | player_id、expected_version、avatar_asset_id；头像为空恢复固定默认 | 200 CharacterView；检查独立 appearance_version |
| PATCH /api/communities/{community_id}/status | player_id、status（active／paused）、expected_version 必填；要求玩家属于社群 | 200 PublicCommunityView；版本过期返回 409 |
| PUT /api/communities/{community_id}/players/{player_id} | 无正文，当前测试玩家加入 | 200 两个身份字段 |
| GET /api/communities | player_id 必填；scope=joined 或 available，默认 joined；分页 | 200 Page[CommunityCard] |
| GET /api/communities/{community_id} | player_id 必填，要求属于社群 | 200 PublicCommunityView |
| GET /api/communities/{community_id}/events/cursor | player_id 必填，要求属于社群 | 200 CursorResponse |
| GET /api/communities/{community_id}/events | player_id 必填；cursor 或 Last-Event-ID 必须提供，详见事件参考 | 200 text/event-stream |
| GET /api/communities/{community_id}/members | player_id 必填，要求属于社群；分页 | 200 Page[PublicDisplay] |
| GET /api/blueprints | 无 | 200 BlueprintView 数组 |
| POST /api/communities/{community_id}/characters | player_id、blueprint_id 必填；character_id 可选；memory_mode 默认 simple，可选 full | 201 CharacterView |
| GET /api/communities/{community_id}/characters | player_id 必填，要求属于社群 | 200 CharacterView 数组 |
| POST /api/communities/{community_id}/characters/{character_id}/memory/retry | player_id 必填，要求具有实例创建资格 | 200 CharacterView |
| POST /api/communities/{community_id}/conversations | player_id、kind、actors 必填；conversation_id 可选；发起者必须在 actors 中 | 201 ConversationView |
| GET /api/conversations | player_id 必填；community_id 可选；membership=current/past/all，默认 current；status=active/archived/all，默认 active；分页 | 200 Page[PlayerConversationSummary] |
| GET /api/conversations/{conversation_id} | player_id 必填，要求有真实参与历史 | 200 PlayerConversationSummary |
| GET /api/conversations/{conversation_id}/members | player_id 必填，要求当前成员；分页 | 200 Page[PublicDisplay] |
| PUT /api/conversations/{conversation_id}/membership | player_id、client_operation_id 必填；自身重新加入 | 200 MembershipResult |
| DELETE /api/conversations/{conversation_id}/membership | 查询 player_id、expected_membership_id、client_operation_id 必填 | 200 MembershipResult |
| POST /api/conversations/{conversation_id}/messages | SendMessage | 202 MessageReceipt |
| GET /api/conversations/{conversation_id}/messages | player_id 必填；cursor 可选；limit 默认 50，1—200 | 200 MessagePageView |
| GET /api/conversations/{conversation_id}/messages/history | player_id 必填；older_cursor 可选；limit 默认 50，1—200 | 200 MessageHistoryView |
| GET /api/conversations/{conversation_id}/messages/{message_id} | player_id 必填，消息必须可见 | 200 PlayerMessageView |
| PUT /api/conversations/{conversation_id}/read | player_id、through_message_id 必填 | 200 ReadState |
| GET /api/conversations/{conversation_id}/turns | player_id 必填；limit 默认 50，1—200 | 200 TurnView 数组 |

PublicCommunityView 在 CommunityView 的正式社群字段之外提供 capabilities，包含 can_change_cover 与 can_change_status。含义与成员资格规则见 [社群读取](../design/identity-and-communities.md#6-读取与变化边界)。管理读取继续使用 CommunityView。

社群全量会话列表及指定任意主体的会话成员操作使用 [管理接口](management-api.md)。玩家读取不需要请求管理路径。世界时间管理、会话归档、活动和手动反思没有公开写入入口。

## 3. 消息与三种分页位置

SendMessage 必填 player_id、client_message_id、非空 text。新消息面向发送时的会话成员，请求不接受 visibility 或 recipients；携带任一字段返回 422。mentions 默认空，reply_to_message_id 可空，回复来源必须对发送者可见。与部分成员交流时创建包含这些成员的独立会话。复用历史私有消息的 client_message_id 返回 409 idempotency_conflict。

MessageReceipt 包含 message_id、conversation_id、sequence、trace_id。202 表示消息接受，后台独立生成回应。相同玩家、客户端标识和内容返回原事实，内容不同返回 409 idempotency_conflict，不延长输入窗口。

PlayerMessageView 包含原消息字段 message_id、conversation_id、sequence、sender、text、visibility、mentions、reply_to_message_id、source_turn_id、created_at_utc，增加 sender_display、recipients、reply_preview。历史私有消息的 recipients 表达发生时实际接收主体；新消息 visibility 固定为 conversation，recipients 为空数组。旧轮次恢复生成的回应沿用原范围。reply_preview 仅在引用对阅读者可见时提供，包含短预览；不可见引用不返回正文。消息不含 Thought、记忆、模型提示或内部任务状态。

| 协议 | 响应和使用 |
|---|---|
| 对象列表 | items、cursor、has_more；结束 cursor=null；改变筛选回到第一页 |
| 消息增量 | messages、cursor、has_more；一页限制扫描数量，过滤后可以为空且有下一页；无新消息保留返回游标；用于增量补充，也支持现有轮询客户端 |
| 最新和历史 | messages、older_cursor、has_older、poll_cursor；首次不传 older_cursor，取得最新可见消息；首次 poll_cursor 建立增量位置；后续历史页 poll_cursor=null |

消息均按序号升序显示。历史按可见消息数量限制，固定首次读取终点；更早消息用 older_cursor，新消息用增量 cursor。空历史仍给出有效 poll_cursor。游标原样传递，前端不解析，不能跨玩家、会话或协议使用。

## 4. 会话概要、阅读与成员

PlayerConversationSummary 包含原 ConversationView 字段及 display_name、self_membership_status、self_membership_id、can_send、direct_peer、last_message、last_visible_message_at_utc、last_read_sequence、unread_count。预览 text_preview 最多 160 个字符。列表按可见活动排序，不携带全局 next_sequence。

display_name 由后端读取时生成：私聊使用对方角色名称；群聊按成员加入时间与成员区间编号排序，使用除阅读者外的前三位当前成员名称，超过三位附「等 N 人」，没有其他成员时为「只有你」。已离开的群聊显示「已离开的群聊」，避免透露当前成员。列表和会话详情使用同一规则；成员列表只用于头像、人数和提及候选。当前没有自定义会话名称或名称写入接口。

ReadState 包含 conversation_id、last_read_sequence、unread_count。已读请求必须指定实际可见消息；位置只向前推进。未读统计其他主体的实际可见消息；自己的消息、不可见私人消息和离开期间消息不计入。列表、消息和轮询读取不自动标记已读。旧会话初始阅读位置为 0。

MembershipResult 包含实际 membership、操作完成时 membership_version、self_membership_status。重复操作返回原结果；新状态另读会话详情。membership 包含真实成员区间编号、主体、加入离开序号与时间。自身退出绑定 expected_membership_id；管理变更绑定 expected_membership_version。client_operation_id 同内容重复复用，不同内容冲突。直接会话固定原始玩家与角色，双方离开后可以分别恢复。

TurnView 包含 input_message_ids、status、participation、完成时间，以及 chain_id、parent_turn_id、depth、stop_reason、chain_status、chain_stop_reason。群聊单次安排完成时，接话链仍可能 active；整条链 completed 或 cancelled 才结束。私聊及升级前旧轮次的链条字段为空，depth 为 0。只有当前来源及根来源均对玩家可见时返回。selection_order 表示实际安排次序，等待候选不提前写成模型沉默。沉默、失败和异步回应不触发玩家消息自动重发。

BlueprintView 增加可空 avatar_url。CharacterView 增加 display_name、avatar_url，按实例绑定的模板版本取得。

CharacterView 包含 memory_mode（simple／full）、memory_status（preparing／ready／failed）和可空 memory_phase。memory_error_code 由管理响应提供。模式创建后不可切换。同一 character_id 必须绑定相同人物版本与模式；重复请求返回当前实例。作者故事或采访存在时进入 preparing；仅有基础人设直接 ready。准备未完成时创建会话或加入会话返回 409 character_memory_not_ready。准备重试仅把 failed 恢复为 preparing，保留已有材料和成功结果；其他状态重复请求返回当前状态。

## 5. 错误与健康

业务错误为 `{"error":{"code":"...","message":"..."}}`，422 保持 FastAPI detail 数组。

| 状态与代码 | 意义 |
|---|---|
| 400 invalid_request / invalid_cursor | 业务输入或游标无效 |
| 404 not_found 或具体对象代码 | 对象不存在或不属于读取、操作范围 |
| 409 stage_dependency_unmet | 按顺序确认基础和已使用阶段 |
| 409 interview_incomplete | 选题十至十五题，完成全部回答 |
| 409 documents_review_required | 审核当前三份正文或接受无冲突校准 |
| 409 calibration_conflict | 作者修正冲突，重新校准或手工审核正文 |
| 409 idempotency_conflict | 同一消息或成员操作标识用于不同内容 |
| 409 membership_version_conflict | 管理成员版本已经变化 |
| 409 membership_interval_conflict | 自身退出的成员区间已经变化 |
| 409 conversation_archived | 归档不允许发送或加入 |
| 409 conflict | 其他既有业务冲突 |
| 500 invalid_response / storage_unavailable | 内部响应或非重试存储故障 |
| 503 storage_unavailable | 可重试存储故障 |

GET /health/live 返回 status、service、version；GET /health/ready 返回 status、database、workers_enabled、workers，健康时 200，否则 503。两者不请求模型。

接入过程见 [前端指南](../guides/frontend-integration.md)，私人材料和恢复诊断见 [管理参考](management-api.md)。

## 6. 自定义人物创作

创作接口使用本地 player_id 检查所有者。完整资料仅作者可读取。草稿与自定义人物列表默认 limit=20，范围 1—100，沿用 items、cursor、has_more。GET /api/blueprints 保持公共预置目录语义。

| 方法与路径 | 输入 | 成功响应 |
|---|---|---|
| GET /api/character-authoring/template | 无 | 200 默认正文、引导、采访题库、提醒、操作说明与请求规模限制 |
| POST /api/character-drafts | player_id、draft_id（UUID）、display_name、description；可选 story、interview、profile、voice、relational_dynamics、avatar_url | 201 DraftView；重复同请求返回 200 |
| GET /api/character-drafts | player_id、列表分页 | 200 Page[DraftView] |
| GET /api/character-drafts/{draft_id} | player_id | 200 DraftView |
| PUT /api/character-drafts/{draft_id} | player_id、expected_revision、完整 content，作为作者手工编辑 | 200 DraftView |
| POST /api/character-drafts/{draft_id}/candidates | player_id、candidate_id（UUID）、expected_revision、operation；可选 instruction、question_ids | 201 CandidateView；重复同请求返回 200 已保存状态 |
| GET /api/character-drafts/{draft_id}/candidates/{candidate_id} | player_id | 200 CandidateView |
| POST /api/character-drafts/{draft_id}/candidates/{candidate_id}/accept | player_id、expected_revision | 200 DraftView，按操作范围合并 |
| POST /api/character-drafts/{draft_id}/stages/{stage}/confirm | player_id、expected_revision；stage 为 basic、story、interview | 200 DraftView |
| POST /api/character-drafts/{draft_id}/documents/template | player_id、expected_revision | 200 TemplateDocumentsView，含 input_revision 与 BasicOutput；不修改草稿 |
| POST /api/character-drafts/{draft_id}/documents/template/accept | player_id、预览使用的 expected_revision | 200 DraftView；复核版本并接受确定性模板正文 |
| POST /api/character-drafts/{draft_id}/documents/confirm | player_id、expected_revision、acknowledge_documents_match=true | 200 DraftView |
| POST /api/character-drafts/{draft_id}/confirm | player_id、expected_revision、acknowledge_fixed_background=true | 201 CustomBlueprintView；重复确认返回 200 |
| POST /api/character-drafts/{draft_id}/copy | player_id、新的 draft_id（UUID） | 201 DraftView；重复复制返回 200 |
| GET /api/custom-blueprints | player_id、列表分页 | 200 Page[BlueprintCard] |
| GET /api/custom-blueprints/{blueprint_id} | player_id | 200 CustomBlueprintView |

DraftView 包含 draft_id、owner_player_id、status、revision、content、workflow、confirmed_blueprint_id、accepted_candidate_id、material_processing 及创建和更新时间。content 保存原文与三份运行正文，采访项为 question_id、question、answer。创建只需 display_name，description 可以留空；introduction 的五组资料及字段限制见 [创作设计](../design/custom-character-authoring.md#2-作者操作与三份运行正文)。默认正文只组织名字和基础描述；提前写入的故事和采访原文独立保存。组合内容不合法返回 400 authoring_input_invalid，字段格式和范围错误返回 422。

workflow 保存 basic、story、interview 阶段状态，取值为 pending（待确认）、accepted（已确认）、review_required（需要复核）、unused（未使用）；基础不会设为 unused。documents_review 为 review_required 或 accepted。interview_basis 保存开始采访时的共同规则、表达指导、人物正文、基础描述、名字、自介和故事，建立后各批沿用；修改基础、故事、作者正文或名字，或者删除整份采访时清除依据。

CandidateView 包含 candidate_id、draft_id、input_revision、operation、status、output、frozen_input、model_profile、model_requests、usage、deadline_utc、created_at_utc、finished_at_utc。error_code 由管理响应提供。status 为 processing、completed 或 failed。frozen_input 保存本次请求、完整材料、流程状态、问题、实际采访依据和模型配置。生成同步等待并独立保存候选，接受前不改变作者材料。

| operation | 请求补充字段 | output |
|---|---|---|
| basic（基础） | 可选 instruction | operation、description、profile、voice、relational_dynamics、changes |
| story（故事） | 可选 instruction；基础已确认 | operation、story、changes |
| interview（采访） | question_ids 为已选题目的一至五个唯一编号；可选 instruction | operation、answers（question_id、answer）、new_background_suggestions |
| calibrate（校准） | 可选 instruction；已使用阶段均已确认 | operation、profile、voice、relational_dynamics、changes、conflicts |

校准的 changes 每项包含 document、explanation、source_refs；conflicts 每项包含 explanation、source_refs。来源只允许 description、story、profile、voice、relational_dynamics、interview:<question_id>、introduction:<字段路径>，且必须存在于冻结材料；自介引用仅允许实际非空字段。存在冲突的候选可以读取，接受返回 calibration_conflict。作者可以修正材料重新校准，或手工决定当前正文并审核。

采访先在 content.interview 中保存十至十五道选题及题目原文，回答可以为空。默认十五题或作者自定义问题均可使用；question_id 必须唯一。开始采访要求基础与故事已确认、正文已审核；后续批次沿用已有依据，文档因回答变化待审核时仍能继续。阶段确认要求全部选题都有非空回答，拒答同样有效。回答没有目标字数或最低字数要求，answer 的 2000 字符上限只控制请求规模。

接受候选由独立入口按类型合并，不提交全量 content。材料接受后通过阶段确认；校准接受直接审核三份正文，保持输入阶段的确认状态。作者 PUT 改写正文属于上游修改，会要求后续材料复核。重复保存或确认且没有变化时不推进 revision；接受候选推进 revision，同一已接受候选在接受后的当前版本重复请求返回原草稿，之后版本变化则视为过期。

最终固定要求基础及已使用阶段均已确认，三份正文已审核。可以在基础或故事阶段结束，也可以明确删除未完成的整份采访。相同候选编号和同请求返回已保存状态，包括处理中和失败；重新生成使用新编号。

CustomBlueprintView 包含 blueprint_id、content_version、source_draft_id、owner_player_id、display_name、avatar_url、content、material_processing、created_at_utc；BlueprintCard 不含 content。确认后内容固定。已有 POST /api/communities/{community_id}/characters 使用返回的 custom:<UUID> 创建实例，要求作者属于目标社群。

| 状态与代码 | 处理方式 |
|---|---|
| 409 draft_revision_conflict | 重新读取当前草稿再保存或确认 |
| 409 blueprint_immutable | 复制新草稿继续创作 |
| 409 candidate_stale | 候选未完成或属于旧版本，读取当前草稿重新生成 |
| 409 stage_dependency_unmet | 按顺序确认基础和已使用阶段 |
| 409 interview_incomplete | 选题十至十五题，完成全部回答 |
| 409 documents_review_required | 审核当前三份正文或接受无冲突校准 |
| 409 calibration_conflict | 作者修正冲突，重新校准或手工审核正文 |
| 409 idempotency_conflict | 编号用于不同请求，使用新编号 |
| 502 authoring_output_invalid | 两次请求仍未得到合法输出，保留草稿并使用新候选编号 |
| 503 authoring_model_unavailable | 检查配置或模型服务，再使用新候选编号 |
| 504 authoring_timeout | 整体生成超过 90 秒，保留草稿并读取候选状态 |

生成失败响应另带 candidate_id。中断候选超过截止时间后读取会保存 failed 与 authoring_interrupted。material_processing 固定为 stored_only（仅保存原始材料）。完整规则见 [自定义人物设计](../design/custom-character-authoring.md)。

## 7. 图像资产与生成

资产资料与任务查询要求 player_id 为所有者；图片读取按公开资产编号提供图像。资产规格、来源和引用规则见 [图像资产设计](../design/image-assets.md)。JSON 请求拒绝未知字段，上传使用文件表单。

| 方法与路径 | 请求 | 成功响应 |
|---|---|---|
| GET /api/assets/generation-styles | 无 | 200 风格数组，含 style_id、name、description、purposes |
| POST /api/assets/images | player_id、purpose、file 文件表单；purpose 为插画、封面或聊天背景 | 201 AssetView；实际规格及各档图片地址 |
| POST /api/assets/{asset_id}/avatar-crops | player_id、client_request_id、x、y、size；来源为角色插画 | 201 AssetView；同编号同输入返回原头像，不同输入 409 |
| GET /api/assets | player_id 必填；purpose 可选；cursor、limit 分页 | 200 Page[AssetView] |
| GET /api/assets/{asset_id} | player_id | 200 AssetView |
| GET /api/assets/{asset_id}/images/{variant} | variant 为 standard 或返回的档位编号 | 200 image/webp；不可变缓存、nosniff |
| DELETE /api/assets/{asset_id} | player_id | 204；仍被引用时 409 |
| POST /api/image-generations | player_id、client_request_id、purpose、style_id、scene_context；description 或角色 draft_id 与 revision；appearance 可选 | 202 GenerationView；缺少凭据 503 image_model_unavailable |
| GET /api/image-generations/{generation_id} | player_id | 200 GenerationView |

scene_context 支持 preset_key、time_of_day、lighting、palette、background_description。生成用途为 character_illustration、community_cover、chat_background，规格由后端决定，请求不接受 resolution。任务按 queued、submitting、generating、saving、completed、failed 表达进展，完成后返回一个 asset_id；裁剪头像使用独立请求。任务不暴露供应商编号、提示、凭据或供应商原始错误。

AssetView 包含 asset_id、owner_player_id、purpose、source、source_asset_id、crop、created_at_utc、images。images 的每项包含 variant、width、height、byte_size、mime、url，所有尺寸都对应实际文件。standard 表示用途标准图；展示档位编号为 540、256、768、1536，按用途返回。上传小图不放大。

cover_kind 为 preset 或 asset，cover_ref 分别为前端预设编号或所属玩家的 community_cover 资产编号；两个字段同时为空表示清除。角色头像字段使用 character_avatar 资产编号。草稿正文支持 avatar_asset_id，与外部 avatar_url 互斥；定稿和复制保留资产身份。CharacterView 提供实例 avatar_asset_id 覆盖值与 appearance_version，未覆盖时为空；公开头像和插画地址来自有效默认或覆盖。
