# 实际后端文件导航

路径相对 `server/src/echo_commons/`。先按业务模块查找，再按领域、服务、存储、接口和任务查找。
入口列直接读取当前 Python 顶层类型与函数；具体职责见 [系统设计](../design/system.md)。
每个 Python 包有明确的 `__init__.py`；包初始化只承担版本声明或包登记，不重复导出业务定义。

重新生成：`uv run python tools/build_file_reference.py`；增加 `--check` 验证当前列表。


## `agents/`

| 文件 | 类型与入口 |
|---|---|
| `agents/authoring.py` | AuthoringUsage, AuthoringFailure, validate_candidate, AuthoringAgent |
| `agents/character/agent.py` | CharacterAgent |
| `agents/contracts/capabilities.py` | AgentPurposeCapabilities, AgentCapabilities, AgentDescriptor |
| `agents/contracts/context.py` | SnapshotModel, SnapshotScope, ObservedMessage, RelationshipView, SelfContext, PerspectiveContext, MemoryItem, HistoricalThought, ConversationSummary, MemoryContext, EnvironmentContext, ContextSnapshot |
| `agents/contracts/errors.py` | ExecutionError |
| `agents/contracts/execution.py` | ExecutionLimits, PreparedExecution |
| `agents/contracts/input.py` | InputModel, ActorScope, ActionSpace, SourceVersion, ToolReadPolicy, InvocationInput |
| `agents/contracts/invocation.py` | InvocationPurpose, InvocationIdentity, InvocationScope, ExecutionPolicy, Correlation, AgentInvocation |
| `agents/contracts/output.py` | CharacterMessageProposal, OutputRegistry |
| `agents/contracts/recovery.py` | FailureCategory, RecoveryAction, FailureInfo, TaskRecoveryDecision |
| `agents/contracts/refs.py` | OutputContractRef, ContextInputRef |
| `agents/contracts/run.py` | AgentRunStatus, AgentStopReason, UsageSummary, ToolActivity, AgentStep, AgentOutput, RepairObservation, AgentRunResult, RunnableAgent |
| `agents/factory.py` | build_character_agent |
| `agents/harness/context.py` | PromptContext, repair_instruction, InputReadiness, InputProjector |
| `agents/harness/loop.py` | utc_now, AgentLoop, _duration_ms |
| `agents/harness/output.py` | ModelOutputError, parse_terminal_output |
| `agents/harness/policy.py` | HarnessPolicy |
| `agents/harness/progress.py` | ToolProgressExtractor, ProgressObservation, ToolProgressState |
| `agents/harness/prompt.py` | read_prompt_resource, render_expression_guidance, render_prompt_section, _clean, render_persona, render_identity, render_state, render_relationships, render_memory, render_memory_items |
| `agents/harness/recovery.py` | classify_model_output_error, classify_gateway_error, classify_tool_error, repair_hint_for |
| `agents/harness/runner.py` | HarnessBackend |
| `agents/harness/state.py` | HarnessControlState, AgentRunState |
| `agents/harness/tools.py` | ToolExecutionError, ToolAuthorizationError, ToolContext, ToolResult, ReadOnlyTool, ToolRegistration, ToolRegistry |

## `app/`

| 文件 | 类型与入口 |
|---|---|
| `app/cli.py` | execute, main |
| `app/composition.py` | Application, assemble |
| `app/development.py` | ExamplePlayer, ExampleCharacter, ExampleCommunity, initialize_example, inspect_database, export_database |
| `app/health.py` | ready |
| `app/http.py` | RequestModel, ErrorBody, ErrorResponse, application_for, register_errors |
| `app/lifecycle.py` | application_lifecycle, lifespan_for |
| `app/main.py` | create_app |
| `app/management.py` | page_options, characters, conversations, join_member, leave_member, communities, community, players, player, community_members, character, states, relationships, evidence, conversation, members, messages, message, turns, turn, tasks, task, context, memory_index, rebuild_memory_index, memory_records, memory_record, reflection_runs, reflection_run, node_input, traces, seal, schedule_segment, schedule_summaries, restart, export |
| `app/management_schemas.py` | View, CommunityMemberView, CharacterDetail, StateView, StateInspection, RelationshipInspection, EvidenceView, ConversationDetail, MemberInterval, MessageSummary, AudienceMember, MessageDetail, TurnSummary, ParticipationDetail, TurnDetail, RecoverySummary, ExecutionEventView, TaskSummary, InspectedThought, InspectedMemory, InspectedContext, ConversationMessageContent, ConversationMessageOutput, ConversationMessageResult, ConversationSilentResult, ConversationResultView, TaskDetail, SourceView, CoverageView, ConsumptionView, SegmentSummary, SegmentDetail, BatchSource, BatchView, DigestSummary, DigestDetail, EntrySummary, EntityLink, MemoryLink, EntryDetail, EntitySummary, AliasView, EntityDetail, EdgeView, ReflectionSummary, InspectedThoughtMaterial, InspectedGraph, InspectedNode, NodeInspection, ArtifactView, ReflectionResultView, TraceView, TraceInspection, SupplementView, ReflectionDetail, SealRequest, SealResult, SegmentReflectionRequest, SummaryReflectionRequest, ScheduleResult, ExportRequest, ExportScope, SourceReference, ThoughtView, ExportView |
| `app/settings.py` | Settings, load_settings |

## `execution/`

| 文件 | 类型与入口 |
|---|---|
| `execution/clock.py` | utc_now |
| `execution/contracts.py` | TaskLease, Disposition, ExecutionOutcome, TaskQueue, TaskHandler |
| `execution/dispatcher.py` | TaskDispatcher |
| `execution/errors.py` | ExecutionDeferred |
| `execution/lease.py` | LeaseLostError, with_heartbeat |
| `execution/model_budget.py` | ModelBudget |
| `execution/observations.py` | ExecutionObservation, ExecutionEventPayload |
| `execution/records.py` | ExecutionRecorder |
| `execution/recovery.py` | QueuePolicy, AppliedRecovery, decision, RecoveryPolicy, decide_run |
| `execution/registry.py` | TaskRegistry |
| `execution/supervisor.py` | Worker, WorkerState, Supervisor |
| `execution/workers/conversations.py` | ConversationWorker |
| `execution/workers/reflection.py` | ReflectionWorker |
| `execution/workers/social.py` | SocialWorker |
| `execution/workers/traces.py` | TraceWorker |

## `infrastructure/`

| 文件 | 类型与入口 |
|---|---|
| `infrastructure/database/connection.py` | Database |
| `infrastructure/database/errors.py` | StorageError |
| `infrastructure/database/execution_records.py` | ExecutionRecordRepository |
| `infrastructure/database/mapping.py` | utc_text, utc_datetime |
| `infrastructure/database/migrations.py` | initialize |
| `infrastructure/models/embeddings.py` | EmbeddingGateway |
| `infrastructure/models/errors.py` | classify_configuration_error, classify_provider_error, _retry_after_seconds |
| `infrastructure/models/metrics.py` | ProviderUsageTracker |
| `infrastructure/models/openai_compatible.py` | OpenAICompatibleGateway, _default_client_factory, _request_params, _prompt_message_payload, normalize_completion, normalize_usage, _collect_stream, _retry_delay, _field, _first_int, _parse_tool_arguments, _optional_string, _string_or_default, _duration_ms |
| `infrastructure/models/protocol.py` | ModelResponseKind, PromptMessage, ToolCall, ModelRequest, ModelResponse, ModelGatewayError, ModelGateway |
| `infrastructure/models/registry.py` | ModelConfigurationError, ModelCredentialError, ModelEntry, ModelRegistry, load_model_registry, _read_toml, _mapping, _required_string, _string, _bool, _positive_float, _non_negative_float, _positive_int, _non_negative_int, _optional_float |
| `infrastructure/models/routing.py` | ModelRoute, TaskRouting |
| `infrastructure/observability/debug_capture.py` | AgentDebugCapture, render_model_request, run_with_debug_capture, _safe_capture, _invocation_correlation, _agent_run_result_json, _error_details, _safe_name, _timestamp, _jsonable |
| `infrastructure/observability/logging.py` | JsonLogFormatter, get_logger, close_logging, configure_logging, log_event, _remove_owned_handlers, _mark_owned, _resolve_level, _safe_scalar |
| `infrastructure/observability/outbox.py` | enqueue_trace, claim_traces, deliver_trace, fail_trace |
| `infrastructure/observability/query.py` | read_traces, TraceQuery |
| `infrastructure/observability/trace_delivery.py` | TraceDelivery |

## `modules/characters/`

| 文件 | 类型与入口 |
|---|---|
| `modules/characters/api/authoring_routes.py` | template, create, drafts, draft, update, confirm, copy, blueprints, blueprint, generate, candidate, confirm_stage, confirm_documents, accept_candidate |
| `modules/characters/api/authoring_schemas.py` | CreateDraft, UpdateDraft, ConfirmDraft, CopyDraft, CandidatePlayer, GenerateBasic, GenerateStory, GenerateInterview, GenerateCalibrate, DraftAction, ConfirmDocuments, DraftView, BlueprintCard, CustomBlueprintView, CandidateView, CandidateError, GuidanceQuestion, AuthoringTemplateView |
| `modules/characters/api/routes.py` | list_blueprints, create_character, list_characters, retry_memory |
| `modules/characters/api/schemas.py` | CreateCharacter, RetryMemory, BlueprintView, CharacterView |
| `modules/characters/contracts.py` | InstanceReader, StateReader, CharacterIdentityReader, CharacterFactWriter |
| `modules/characters/domain/authoring.py` | AuthoringModel, InterviewAnswer, PersonaDocuments, AuthoringContent, InterviewBasis, AuthoringWorkflow, CandidateBase, BasicRequest, StoryRequest, InterviewRequest, CalibrateRequest, BasicOutput, StoryOutput, InterviewResponse, InterviewOutput, CalibrationChange, CalibrationConflict, CalibrateOutput, merge_candidate, DraftRevisionConflict, BlueprintImmutable, CandidateStale, StageDependencyUnmet, InterviewIncomplete, DocumentsReviewRequired, CalibrationConflictError, InterviewSelectionInvalid |
| `modules/characters/domain/changes.py` | RelationshipChange, StateChange |
| `modules/characters/domain/instance.py` | MemoryMode, MemoryStatus, AvailabilityStatus, CharacterInstance |
| `modules/characters/domain/relationship.py` | _score, RelationshipTargetKind, RelationshipType, RelationshipDimension, RelationshipDirection, RelationshipEvidenceKind, RelationshipKey, RelationshipValues, RelationshipState, RelationshipEvidence, RelationshipImpact, RelationshipStepMultiplier, RelationshipPolicy, RelationshipAttitude, AppliedRelationshipImpact, RelationshipTransition, apply_relationship_evidence |
| `modules/characters/domain/state.py` | StateKind, StateEntry |
| `modules/characters/management.py` | CharacterManagement |
| `modules/characters/repositories/authoring.py` | AuthoringRepository, draft_view, candidate_view |
| `modules/characters/repositories/instances.py` | InstanceRepository |
| `modules/characters/repositories/relationships.py` | RelationshipRepository |
| `modules/characters/repositories/state.py` | StateRepository |
| `modules/characters/services/authoring.py` | CharacterAuthoring, build_blueprint |
| `modules/characters/services/blueprints.py` | BlueprintReader |
| `modules/characters/services/bootstrap.py` | CharacterBootstrap |
| `modules/characters/services/capabilities.py` | CapabilityResolver |
| `modules/characters/services/context.py` | CharacterContextBuild, CharacterContext |
| `modules/characters/services/facts.py` | reflection_relationship_policy, CharacterFacts |
| `modules/characters/services/identity.py` | CharacterIdentity |
| `modules/characters/services/registry.py` | AgentBindingError, AgentPurposeBinding, AgentRegistry |
| `modules/characters/services/state.py` | CharacterStateService |
| `modules/characters/templates/authoring.py` | authoring_template, default_content |
| `modules/characters/templates/catalog.py` | IdentityResource, IdentityCapability, CapabilitiesResource, AuthoredMemory, MemoryPreloadResource, CharacterBlueprint, BlueprintCatalog |
| `modules/characters/templates/loader.py` | IdentityConfigurationError, load_blueprint_catalog, _load_root, _load_character_manifest, _load_resource, _load_capabilities_resource, _load_memory_preload_resource, _resource_spec, _resolve_resource_path, _resolve_file_path, _child_path, _read_frontmatter, _read_yaml_mapping, _safe_load, _mapping, _required_mapping, _reject_unknown_keys, _required_int, _required_string, _optional_string, _optional_ratio, _required_content_version, _validate_status_and_date |

## `modules/communities/`

| 文件 | 类型与入口 |
|---|---|
| `modules/communities/api/routes.py` | create_community, update_community_status, register_player, join_player, players, player, communities, community, members |
| `modules/communities/api/schemas.py` | CreateCommunity, RegisterPlayer, UpdateCommunityStatus, CommunityView, PlayerView, CommunityCard |
| `modules/communities/contracts.py` | CommunityReader, CommunityLifecycle |
| `modules/communities/domain.py` | CommunityStatus, Community, Player |
| `modules/communities/management.py` | CommunityManagement |
| `modules/communities/query.py` | CommunityQuery |
| `modules/communities/repository.py` | CommunityRepository |
| `modules/communities/service.py` | CommunityService |

## `modules/conversations/`

| 文件 | 类型与入口 |
|---|---|
| `modules/conversations/api/routes.py` | create_conversation, conversations, conversation, members, join, leave, send_message, read_messages, history, message, mark_read |
| `modules/conversations/api/schemas.py` | CreateConversation, SendMessage, ConversationView, MembershipView, MessageView, MessageReceipt, MessagePreview, PlayerMessageView, PlayerConversationSummary, ReadMarker, ReadState, JoinMembership, ManageMembership, MessageHistoryView, MessagePageView |
| `modules/conversations/contracts.py` | ConversationReader, MessageReader, ConversationLifecycle |
| `modules/conversations/domain/conversation.py` | ConversationKind, ConversationStatus, validate_members, Conversation, Membership |
| `modules/conversations/domain/input_batch.py` | InputBatch |
| `modules/conversations/domain/message.py` | MessageVisibility, PlayerMessage, Message |
| `modules/conversations/domain/task.py` | TaskStatus |
| `modules/conversations/export.py` | ConversationExport |
| `modules/conversations/management.py` | message_detail, inspected_result, ConversationManagement |
| `modules/conversations/member_operations.py` | MembershipOperation, MembershipResult |
| `modules/conversations/repositories/conversations.py` | ConversationRepository |
| `modules/conversations/repositories/input_batches.py` | InputBatchRepository |
| `modules/conversations/repositories/member_operations.py` | MembershipOperationRepository |
| `modules/conversations/repositories/messages.py` | MessageRepository |
| `modules/conversations/repositories/queue.py` | ConversationQueueRepository |
| `modules/conversations/repositories/results.py` | ConversationResultRepository |
| `modules/conversations/repositories/tasks.py` | ConversationTaskRepository |
| `modules/conversations/services/batching.py` | InputCollector |
| `modules/conversations/services/conversation.py` | ConversationService |
| `modules/conversations/services/intake.py` | MessageIndexer, MessageIntake |
| `modules/conversations/services/player_query.py` | HistoryCursor, PlayerConversationQuery |
| `modules/conversations/services/query.py` | MessagePage, MessageQuery |
| `modules/conversations/tasks/commit.py` | CommitReceipt, ConversationCommit |
| `modules/conversations/tasks/context.py` | ContextPolicy, ConversationContext |
| `modules/conversations/tasks/diagnostics.py` | ConversationDiagnostics |
| `modules/conversations/tasks/execution.py` | ConversationExecution |
| `modules/conversations/tasks/handler.py` | ConversationHandler |
| `modules/conversations/tasks/lifecycle.py` | TaskLifecycle |
| `modules/conversations/tasks/memory.py` | budget_snapshot, AutomaticMemory |
| `modules/conversations/tasks/prompt.py` | render_conversation_guidance, project_snapshot, render_snapshot |
| `modules/conversations/tasks/queue.py` | ConversationQueue |
| `modules/conversations/tasks/recovery.py` | ConversationRecovery |
| `modules/conversations/tasks/review.py` | ReviewPolicy, ConversationReview |

## `modules/memory/`

| 文件 | 类型与入口 |
|---|---|
| `modules/memory/contracts.py` | MemoryBootstrapper, MemoryChangeWriter, MemoryViewWriter, MemorySegmentWriter, MemoryContinuityWriter, MemoryOrganizationWriter |
| `modules/memory/domain/authored.py` | AuthorMaterial |
| `modules/memory/domain/batches.py` | AuthorBatch |
| `modules/memory/domain/cycles.py` | PendingMaterials |
| `modules/memory/domain/memory.py` | SegmentStatus, MemorySegment |
| `modules/memory/domain/organization.py` | normalize_alias, MemoryEntryDraft, MemoryEntityDraft, MemoryEdgeDraft |
| `modules/memory/domain/policy.py` | VectorPolicy, RetrievalPolicy, CyclePolicy, MemoryPolicy |
| `modules/memory/domain/sources.py` | SourceKind, MemorySource, source_version |
| `modules/memory/domain/summaries.py` | SummaryConsumer, SummaryReference, SummaryBatch |
| `modules/memory/domain/views.py` | MemoryViewDraft |
| `modules/memory/management.py` | MemoryCollection, MemoryManagement |
| `modules/memory/repositories/author_batches.py` | AuthorBatchRepository |
| `modules/memory/repositories/changes.py` | MemoryChangeRepository |
| `modules/memory/repositories/coverage.py` | CoverageRepository |
| `modules/memory/repositories/entries.py` | MemoryEntryRepository |
| `modules/memory/repositories/graph_search.py` | MemoryGraphSearch |
| `modules/memory/repositories/initialization.py` | InitializationRepository |
| `modules/memory/repositories/organization.py` | MemoryOrganizationRepository |
| `modules/memory/repositories/provenance.py` | MemoryProvenanceRepository |
| `modules/memory/repositories/relationship_evidence.py` | RelationshipEvidenceReader |
| `modules/memory/repositories/search.py` | SearchRepository |
| `modules/memory/repositories/segments.py` | SegmentRepository |
| `modules/memory/repositories/thoughts.py` | ThoughtRepository |
| `modules/memory/repositories/vectors.py` | VectorRepository |
| `modules/memory/services/batches.py` | SummaryBatches |
| `modules/memory/services/bootstrap.py` | MemoryBootstrap |
| `modules/memory/services/continuity.py` | MemoryContinuity |
| `modules/memory/services/indexing.py` | MemoryIndexing |
| `modules/memory/services/ingestion.py` | MemoryIngestion |
| `modules/memory/services/materials.py` | chunk_ranges, MemoryMaterials |
| `modules/memory/services/organization.py` | MemoryOrganization |
| `modules/memory/services/preparation.py` | MemoryPreparation |
| `modules/memory/services/retrieval.py` | SearchScope, SearchHit, MemoryRetrieval, _source_version |
| `modules/memory/services/sealing.py` | MemorySealing |
| `modules/memory/services/tokenization.py` | _normalize_token, _is_searchable, tokenize_text, tokenized_text, fts_match_query |
| `modules/memory/services/vectors.py` | MemoryVectors |
| `modules/memory/services/views.py` | MemoryViews |
| `modules/memory/tools/search.py` | SearchArguments, MemorySearchTool, memory_progress |

## `modules/perspective/`

| 文件 | 类型与入口 |
|---|---|
| `modules/perspective/contracts.py` | ActorNames, ObservationScope, PerspectiveReader, PublicParticipant, Observation, WorldReader |
| `modules/perspective/conversation.py` | ConversationPerspective |
| `modules/perspective/policy.py` | visible_message_sql, can_observe |
| `modules/perspective/reader.py` | WorldPerspective |

## `modules/reflection/`

| 文件 | 类型与入口 |
|---|---|
| `modules/reflection/contexts/actors.py` | source_actors |
| `modules/reflection/contexts/authors.py` | author_snapshot |
| `modules/reflection/contexts/graph.py` | ReflectionContextPolicy, GraphContext |
| `modules/reflection/contexts/segment.py` | SegmentContext |
| `modules/reflection/contexts/sources.py` | ReflectionSourceUnavailable, ReflectionSources |
| `modules/reflection/contexts/summaries.py` | SummaryContext |
| `modules/reflection/contracts/candidates.py` | ReflectionCandidateKind, ReflectionBatchOutcome, ReflectionNodeActionKind, FollowUpDecision, _normalize_source_refs, EvidenceRef, _normalize_model_evidence_refs, ReflectionCandidateBase, SegmentSummaryCandidate, MemoryUpsertCandidate, ContinuityDigestCandidate, DiaryAppendCandidate, CoreMemoryRewriteCandidate, ViewRewriteCandidate, StateEntryCandidate, RelationshipImpactCandidate, EntityAliasCandidate, MemoryEntityCandidate, MemoryEdgeCandidate, ReflectionNodeActionBase, SegmentSummaryAction, RelationshipDimensionAction, RelationshipReflectionAction, StateReflectionAction, ContinuityDigestAction, LongTermMemoryPageItem, LongTermMemoryPageAction, GraphEntityAction, GraphEdgeAction, GraphExtractionAction, DiaryAction, ViewRefreshAction, NoOpReflectionAction, ReflectionBatchProposal |
| `modules/reflection/contracts/context.py` | ReflectionModel, MaterialSource, MessageMaterial, ThoughtMaterial, SummaryMaterial, DigestMaterial, AuthorMaterialSource, FactMaterial, GraphContextSnapshot, ArtifactInput, ReflectionNodeInput |
| `modules/reflection/coordinator.py` | ReflectionCoordinator |
| `modules/reflection/diagnostics.py` | ReflectionRunView |
| `modules/reflection/domain/graph.py` | _positive_integer, _non_negative_integer, _normalize_unique_strings, FrozenPayload, _freeze_json_value, _thaw_json_value, _canonical_json, ContentFingerprint, content_fingerprint, OutputContractRef, GraphSourceRef, ReflectionSourceScope, EvidenceRef, normalize_evidence_refs, ArtifactRef, ReflectionLease, ReflectionGraphKind, ReflectionNodeKind, ReflectionExecutionKind, ReflectionDependencyMode, ReflectionGraphRunStatus, ReflectionDependency, ReflectionNodeDefinition, ReflectionGraphDefinition, ReflectionGraphRun, ReflectionArtifact, register_artifact, validate_unique_node_tasks, _contract, reflection_graph_definition |
| `modules/reflection/domain/node.py` | ReflectionNodeTaskStatus, _integer, ReflectionNodeTask, activate_successor |
| `modules/reflection/domain/result.py` | GraphReviewStatus, GraphReviewRecord |
| `modules/reflection/domain/rules.py` | ReflectionOutcome, RelationshipProposalDirection, RelationshipDimensionProposal, _coerce_relationship_dimension, normalize_relationship_dimensions, validate_relationship_dimensions, ReflectionOutcomeDecision, validate_reflection_outcome, validate_no_op, should_activate_follow_up |
| `modules/reflection/initialization.py` | FullMemoryInitialization |
| `modules/reflection/policy.py` | require_graph, allows_follow_up |
| `modules/reflection/registry.py` | ReflectionGraphRegistry |
| `modules/reflection/repositories/artifacts.py` | ArtifactRepository |
| `modules/reflection/repositories/diagnostics.py` | ReflectionDiagnosticsRepository |
| `modules/reflection/repositories/nodes.py` | NodeRepository |
| `modules/reflection/repositories/results.py` | ResultRepository |
| `modules/reflection/repositories/runs.py` | source_scope_fingerprint, RunRepository |
| `modules/reflection/scheduling.py` | MemoryScheduling |
| `modules/reflection/supplements.py` | supplement |
| `modules/reflection/tasks/aggregate.py` | aggregate_artifacts |
| `modules/reflection/tasks/commit.py` | ReflectionNodeCommit |
| `modules/reflection/tasks/dependencies.py` | bind_ready_inputs |
| `modules/reflection/tasks/errors.py` | ReflectionReviewError |
| `modules/reflection/tasks/executor.py` | ReflectionExecution |
| `modules/reflection/tasks/facts.py` | ReflectionFacts |
| `modules/reflection/tasks/graph_commit.py` | ReflectionGraphCommit |
| `modules/reflection/tasks/graph_review.py` | GraphReview |
| `modules/reflection/tasks/handler.py` | ReflectionHandler |
| `modules/reflection/tasks/input.py` | prepare_node_input |
| `modules/reflection/tasks/planner.py` | plan_views |
| `modules/reflection/tasks/projection.py` | NodePromptProjection, select_node_materials, project_node_input |
| `modules/reflection/tasks/prompt.py` | render_node_task, render_material, project_node |
| `modules/reflection/tasks/queue.py` | ReflectionQueue |
| `modules/reflection/tasks/readiness.py` | ReflectionInputReadiness |
| `modules/reflection/tasks/recovery.py` | ReflectionRecovery |
| `modules/reflection/tasks/review.py` | ReflectionReview |
| `modules/reflection/views.py` | ViewScheduling |
| `modules/reflection/workflow.py` | ReflectionWorkflow |

## `modules/social/`

| 文件 | 类型与入口 |
|---|---|
| `modules/social/api/routes.py` | read_turns |
| `modules/social/api/schemas.py` | ParticipationView, TurnView |
| `modules/social/completion.py` | TurnCompletion |
| `modules/social/domain.py` | TurnStatus, ParticipationStatus, ParticipationDecision, SocialTurn |
| `modules/social/participation.py` | Candidate, choose |
| `modules/social/planner.py` | TurnPlanner |
| `modules/social/query.py` | VisibleTurn, TurnQuery |
| `modules/social/repository.py` | SocialRepository |

## `shared/`

| 文件 | 类型与入口 |
|---|---|
| `shared/actors.py` | ActorKind, ActorRef, CommunityScope |
| `shared/errors.py` | BusinessError, NotFoundError, ConflictError, IdempotencyConflict, CharacterNotReady, MembershipVersionConflict, MembershipIntervalConflict, ConversationArchived, InvalidCursor |
| `shared/inspection.py` | redact_thoughts |
| `shared/management.py` | ManagementModel, Page, PageOptions, PageCursor, read_page, json_fields |
| `shared/message_sources.py` | SystemSourceKind, SystemSource, message_source_id |
| `shared/public.py` | PublicDisplay |
| `shared/validation.py` | DomainInvariantError, require_non_empty, require_utc, optional_utc, require_sequence |

## 工程与资源

配置、模型凭据与命令见 [服务说明](../../README.md)。
resources/identity 保存完整模板、声音风格和初始记忆；resources/config 保存非秘密配置模板；
resources/prompts 保存聊天与反思提示正文；resources/authoring 保存创作模板、采访题库与创作提示；
resources/examples/group.json 保存显式示例。正式 SQL 与实际字段见 [数据库](database-schema.md)。
tests/infrastructure 保存真实 SQLite、服务、HTTP、进程恢复和模型验证。
tools 保存安装验证与文档生成命令；阶段记录保存实际验证结果。
