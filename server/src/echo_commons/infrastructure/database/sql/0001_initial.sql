-- 社群、玩家和角色实例
CREATE TABLE communities (
    community_id TEXT PRIMARY KEY NOT NULL,
    name TEXT NOT NULL CHECK(length(trim(name)) > 0),
    timezone TEXT NOT NULL,
    world_time_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','paused')),
    state_version INTEGER NOT NULL DEFAULT 0 CHECK(state_version >= 0),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL
);
CREATE TABLE players (
    player_id TEXT PRIMARY KEY NOT NULL,
    display_name TEXT NOT NULL CHECK(length(trim(display_name)) > 0),
    created_at_utc TEXT NOT NULL
);
CREATE TABLE community_members (
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    actor_kind TEXT NOT NULL CHECK(actor_kind IN ('player','character')),
    actor_id TEXT NOT NULL, joined_at_utc TEXT NOT NULL,
    PRIMARY KEY(community_id, actor_kind, actor_id)
);
CREATE TABLE character_instances (
    character_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    blueprint_id TEXT NOT NULL, blueprint_version TEXT NOT NULL,
    availability_status TEXT NOT NULL DEFAULT 'available'
        CHECK(availability_status IN ('available','offline','busy')),
    availability_reason TEXT, next_check_at_utc TEXT,
    availability_version INTEGER NOT NULL DEFAULT 0 CHECK(availability_version >= 0),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    UNIQUE(community_id, character_id)
);
CREATE TABLE character_state_entries (
    entry_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    state_kind TEXT NOT NULL CHECK(state_kind IN ('physical','mood','activity')),
    value TEXT NOT NULL, source_kind TEXT NOT NULL, source_ref TEXT NOT NULL,
    state_version INTEGER NOT NULL CHECK(state_version >= 1),
    recorded_at_utc TEXT NOT NULL, expires_at_utc TEXT,
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    CHECK(expires_at_utc IS NULL OR expires_at_utc > recorded_at_utc),
    UNIQUE(character_id, state_kind, state_version),
    UNIQUE(character_id, state_kind, source_kind, source_ref)
);

-- 会话及不可复用的成员区间
CREATE TABLE conversations (
    conversation_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    kind TEXT NOT NULL CHECK(kind IN ('direct','group')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    membership_version INTEGER NOT NULL DEFAULT 0 CHECK(membership_version >= 0),
    next_sequence INTEGER NOT NULL DEFAULT 1 CHECK(next_sequence >= 1),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    UNIQUE(community_id, conversation_id)
);
CREATE TABLE conversation_memberships (
    membership_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    actor_kind TEXT NOT NULL CHECK(actor_kind IN ('player','character')), actor_id TEXT NOT NULL,
    joined_after_sequence INTEGER NOT NULL CHECK(joined_after_sequence >= 0),
    left_at_sequence INTEGER, joined_at_utc TEXT NOT NULL, left_at_utc TEXT,
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    FOREIGN KEY(community_id, actor_kind, actor_id) REFERENCES community_members(community_id, actor_kind, actor_id),
    UNIQUE(conversation_id, membership_id),
    UNIQUE(community_id, conversation_id, membership_id),
    CHECK((left_at_sequence IS NULL AND left_at_utc IS NULL) OR
        (left_at_sequence IS NOT NULL AND left_at_utc IS NOT NULL AND
         left_at_sequence >= joined_after_sequence AND left_at_utc >= joined_at_utc))
);

-- 输入和社交轮次：来源通过关联表保存
CREATE TABLE input_batches (
    input_batch_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    sender_kind TEXT NOT NULL CHECK(sender_kind IN ('player','character')), sender_id TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK(visibility IN ('conversation','recipients')),
    audience_json TEXT NOT NULL CHECK(json_valid(audience_json) AND json_type(audience_json) = 'array'),
    status TEXT NOT NULL CHECK(status IN ('collecting','sealed')),
    quiet_until_utc TEXT NOT NULL, sealed_at_utc TEXT,
    origin_turn_id TEXT REFERENCES social_turns(social_turn_id),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    CHECK((status = 'collecting' AND sealed_at_utc IS NULL) OR
          (status = 'sealed' AND sealed_at_utc IS NOT NULL)),
    CHECK(sender_kind != 'character' OR (status = 'sealed' AND origin_turn_id IS NOT NULL)),
    CHECK(sender_kind != 'player' OR origin_turn_id IS NULL),
    UNIQUE(conversation_id, input_batch_id)
);
CREATE TABLE social_turns (
    social_turn_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    audience_json TEXT NOT NULL CHECK(json_valid(audience_json) AND json_type(audience_json) = 'array'),
    visibility TEXT NOT NULL CHECK(visibility IN ('conversation','recipients')),
    observation_max_sequence INTEGER NOT NULL CHECK(observation_max_sequence >= 0),
    membership_version INTEGER NOT NULL CHECK(membership_version >= 0),
    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','cancelled')),
    completion_json TEXT CHECK(completion_json IS NULL OR json_valid(completion_json)),
    created_at_utc TEXT NOT NULL, completed_at_utc TEXT,
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    UNIQUE(community_id, conversation_id, social_turn_id),
    CHECK((status IN ('completed','cancelled') AND completed_at_utc IS NOT NULL AND completion_json IS NOT NULL)
       OR (status IN ('pending','running') AND completed_at_utc IS NULL AND completion_json IS NULL))
);
CREATE TABLE social_turn_batches (
    social_turn_id TEXT NOT NULL REFERENCES social_turns(social_turn_id),
    input_batch_id TEXT NOT NULL UNIQUE REFERENCES input_batches(input_batch_id),
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(social_turn_id, input_batch_id), UNIQUE(social_turn_id, ordinal)
);
CREATE TABLE participation_decisions (
    social_turn_id TEXT NOT NULL REFERENCES social_turns(social_turn_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    reason_code TEXT NOT NULL, selection_order INTEGER CHECK(selection_order >= 0),
    status TEXT NOT NULL CHECK(status IN ('silent','selected','completed','failed','cancelled')),
    outcome TEXT, updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(social_turn_id, character_id),
    CHECK((status = 'selected' AND outcome IS NULL) OR (status != 'selected' AND outcome IS NOT NULL)),
    CHECK((status = 'silent' AND selection_order IS NULL AND outcome = 'silent') OR
          (status = 'selected' AND selection_order IS NOT NULL AND outcome IS NULL) OR
          (status = 'completed' AND selection_order IS NOT NULL AND outcome IN ('message','silent')) OR
          (status = 'failed' AND selection_order IS NOT NULL AND outcome = 'failed') OR
          (status = 'cancelled' AND selection_order IS NOT NULL AND outcome = 'cancelled'))
);

-- 独立角色任务及不可变真实结果
CREATE TABLE conversation_tasks (
    task_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    social_turn_id TEXT NOT NULL, character_id TEXT NOT NULL, membership_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL UNIQUE,
    snapshot_schema_version INTEGER NOT NULL DEFAULT 1 CHECK(snapshot_schema_version = 1),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','processing','retry_wait','suspended','completed','failed','cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0),
    available_at_utc TEXT NOT NULL, lease_owner TEXT, lease_until_utc TEXT, last_error_code TEXT,
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL, trace_id TEXT NOT NULL,
    UNIQUE(social_turn_id, character_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, conversation_id, social_turn_id) REFERENCES social_turns(community_id, conversation_id, social_turn_id),
    FOREIGN KEY(social_turn_id, character_id) REFERENCES participation_decisions(social_turn_id, character_id),
    FOREIGN KEY(community_id, conversation_id, membership_id) REFERENCES conversation_memberships(community_id, conversation_id, membership_id),
    CHECK((status = 'processing' AND lease_owner IS NOT NULL AND lease_until_utc IS NOT NULL)
       OR (status != 'processing' AND lease_owner IS NULL AND lease_until_utc IS NULL))
);
CREATE TABLE conversation_results (
    result_id TEXT PRIMARY KEY NOT NULL, task_id TEXT NOT NULL REFERENCES conversation_tasks(task_id),
    attempt_no INTEGER NOT NULL CHECK(attempt_no >= 1), lease_generation INTEGER NOT NULL CHECK(lease_generation >= 1),
    invocation_id TEXT NOT NULL UNIQUE, output_contract TEXT NOT NULL CHECK(output_contract = 'character_message.v1'),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','expired')),
    decision_code TEXT, created_at_utc TEXT NOT NULL, decided_at_utc TEXT,
    UNIQUE(task_id, attempt_no),
    CHECK((status = 'pending' AND decision_code IS NULL AND decided_at_utc IS NULL) OR
          (status != 'pending' AND decision_code IS NOT NULL AND decided_at_utc IS NOT NULL))
);

-- 完整消息和实际受众；公开消息也保存成员区间
CREATE TABLE messages (
    message_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence >= 1),
    sender_kind TEXT NOT NULL CHECK(sender_kind IN ('player','character','system')), sender_id TEXT NOT NULL,
    sender_membership_id TEXT,
    text TEXT NOT NULL CHECK(length(trim(text)) > 0),
    visibility TEXT NOT NULL CHECK(visibility IN ('conversation','recipients')),
    reply_to_message_id TEXT, client_message_id TEXT,
    source_turn_id TEXT, result_id TEXT UNIQUE REFERENCES conversation_results(result_id),
    trace_id TEXT NOT NULL, created_at_utc TEXT NOT NULL,
    UNIQUE(conversation_id, sequence), UNIQUE(conversation_id, message_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    FOREIGN KEY(conversation_id, sender_membership_id) REFERENCES conversation_memberships(conversation_id, membership_id),
    FOREIGN KEY(conversation_id, reply_to_message_id) REFERENCES messages(conversation_id, message_id),
    FOREIGN KEY(community_id, conversation_id, source_turn_id) REFERENCES social_turns(community_id, conversation_id, social_turn_id),
    CHECK((sender_kind = 'system' AND sender_membership_id IS NULL) OR
          (sender_kind != 'system' AND sender_membership_id IS NOT NULL)),
    CHECK(sender_kind != 'player' OR (client_message_id IS NOT NULL AND result_id IS NULL AND source_turn_id IS NULL)),
    CHECK(sender_kind != 'character' OR (result_id IS NOT NULL AND source_turn_id IS NOT NULL AND client_message_id IS NULL)),
    CHECK(sender_kind = 'player' OR client_message_id IS NULL)
);
CREATE TABLE message_mentions (
    message_id TEXT NOT NULL REFERENCES messages(message_id),
    actor_kind TEXT NOT NULL CHECK(actor_kind IN ('player','character')), actor_id TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(message_id, actor_kind, actor_id), UNIQUE(message_id, ordinal)
);
CREATE TABLE message_recipients (
    message_id TEXT NOT NULL REFERENCES messages(message_id),
    membership_id TEXT NOT NULL REFERENCES conversation_memberships(membership_id),
    PRIMARY KEY(message_id, membership_id)
);
CREATE TABLE input_batch_messages (
    input_batch_id TEXT NOT NULL REFERENCES input_batches(input_batch_id),
    message_id TEXT NOT NULL UNIQUE REFERENCES messages(message_id),
    PRIMARY KEY(input_batch_id, message_id)
);

-- 有向关系和同范围的证据
CREATE TABLE relation_evidence (
    evidence_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, observer_character_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('player','character')), target_id TEXT NOT NULL,
    evidence_kind TEXT NOT NULL CHECK(evidence_kind IN ('interaction','support','conflict','commitment')),
    source_kind TEXT NOT NULL, source_ref TEXT NOT NULL,
    occurred_at_utc TEXT NOT NULL, recorded_at_utc TEXT NOT NULL CHECK(recorded_at_utc >= occurred_at_utc),
    FOREIGN KEY(community_id, observer_character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, target_kind, target_id) REFERENCES community_members(community_id, actor_kind, actor_id),
    UNIQUE(community_id, observer_character_id, target_kind, target_id, source_kind, source_ref),
    UNIQUE(community_id, observer_character_id, target_kind, target_id, evidence_id)
);
CREATE TABLE relationship_state (
    community_id TEXT NOT NULL, observer_character_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('player','character')), target_id TEXT NOT NULL,
    relationship_type TEXT NOT NULL CHECK(relationship_type IN ('stranger','acquaintance','friend')),
    affection REAL CHECK(affection BETWEEN 0 AND 100), trust REAL CHECK(trust BETWEEN 0 AND 100),
    attachment REAL CHECK(attachment BETWEEN 0 AND 100), friend_qualifying_evidence_id TEXT,
    attitude_summary TEXT NOT NULL DEFAULT '',
    attitude_source_refs_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(attitude_source_refs_json) AND json_type(attitude_source_refs_json) = 'array'),
    state_version INTEGER NOT NULL DEFAULT 0 CHECK(state_version >= 0), updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(community_id, observer_character_id, target_kind, target_id),
    FOREIGN KEY(community_id, observer_character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, target_kind, target_id) REFERENCES community_members(community_id, actor_kind, actor_id),
    FOREIGN KEY(community_id, observer_character_id, target_kind, target_id, friend_qualifying_evidence_id)
        REFERENCES relation_evidence(community_id, observer_character_id, target_kind, target_id, evidence_id),
    CHECK((relationship_type = 'stranger' AND affection IS NULL AND trust IS NULL AND attachment IS NULL AND
          friend_qualifying_evidence_id IS NULL AND attitude_summary = '' AND json_array_length(attitude_source_refs_json) = 0) OR
          (relationship_type != 'stranger' AND affection IS NOT NULL AND trust IS NOT NULL AND attachment IS NOT NULL)),
    CHECK(relationship_type != 'friend' OR friend_qualifying_evidence_id IS NOT NULL),
    CHECK((attitude_summary = '' AND json_array_length(attitude_source_refs_json) = 0) OR
          (length(trim(attitude_summary)) > 0 AND json_array_length(attitude_source_refs_json) > 0))
);

-- 实例私有记忆及精确材料
CREATE TABLE memory_segments (
    segment_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    first_message_sequence INTEGER NOT NULL CHECK(first_message_sequence >= 1),
    last_message_sequence INTEGER NOT NULL CHECK(last_message_sequence >= first_message_sequence),
    status TEXT NOT NULL CHECK(status IN ('sealed','ingested')), source_version TEXT NOT NULL,
    summary_text TEXT, summary_version TEXT, sealed_at_utc TEXT NOT NULL, ingested_at_utc TEXT,
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    UNIQUE(character_id, conversation_id, first_message_sequence, last_message_sequence),
    UNIQUE(character_id, conversation_id, segment_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    CHECK((status = 'sealed' AND ingested_at_utc IS NULL) OR (status = 'ingested' AND ingested_at_utc IS NOT NULL)),
    CHECK((summary_text IS NULL AND summary_version IS NULL) OR (summary_text IS NOT NULL AND summary_version IS NOT NULL))
);
CREATE TABLE memory_segment_sources (
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought')), source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(segment_id, source_kind, source_id), UNIQUE(segment_id, ordinal)
);
CREATE TABLE memory_entries (
    memory_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    memory_kind TEXT NOT NULL CHECK(memory_kind IN ('fact','event','preference','promise','thread','other')),
    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
    confidence REAL NOT NULL DEFAULT 1.0 CHECK(confidence BETWEEN 0 AND 1),
    salience REAL NOT NULL DEFAULT 0.5 CHECK(salience BETWEEN 0 AND 1),
    source_kind TEXT NOT NULL, source_ref TEXT NOT NULL, subject_kind TEXT NOT NULL, subject_id TEXT NOT NULL,
    visibility TEXT NOT NULL CHECK(visibility IN ('resident','recallable','private')), content_version TEXT NOT NULL,
    occurred_at_utc TEXT, recorded_at_utc TEXT NOT NULL, expires_at_utc TEXT, invalidated_at_utc TEXT,
    UNIQUE(character_id, memory_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    CHECK(expires_at_utc IS NULL OR expires_at_utc > recorded_at_utc),
    CHECK(invalidated_at_utc IS NULL OR invalidated_at_utc >= recorded_at_utc)
);
CREATE TABLE thoughts (
    thought_id TEXT PRIMARY KEY NOT NULL, result_id TEXT NOT NULL UNIQUE REFERENCES conversation_results(result_id),
    community_id TEXT NOT NULL, character_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    game_day TEXT NOT NULL CHECK(date(game_day) IS NOT NULL AND date(game_day) = game_day),
    content TEXT, content_version TEXT NOT NULL, segment_id TEXT,
    created_at_utc TEXT NOT NULL, content_removed_at_utc TEXT,
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    FOREIGN KEY(character_id, conversation_id, segment_id) REFERENCES memory_segments(character_id, conversation_id, segment_id),
    CHECK((content IS NOT NULL AND length(trim(content)) > 0 AND content_removed_at_utc IS NULL) OR
          (content IS NULL AND content_removed_at_utc IS NOT NULL AND content_removed_at_utc >= created_at_utc))
);
CREATE TABLE memory_source_coverage (
    community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    owner_kind TEXT NOT NULL CHECK(owner_kind IN ('segment_summary','diary')), owner_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought','segment_summary')), source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(character_id, owner_kind, owner_id, source_kind, source_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id)
);
CREATE TABLE memory_summary_batches (
    batch_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    source_version TEXT NOT NULL, previous_digest_id TEXT REFERENCES conversation_digests(digest_id), created_at_utc TEXT NOT NULL,
    UNIQUE(character_id, conversation_id, source_version),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id)
);
CREATE TABLE memory_summary_batch_items (
    batch_id TEXT NOT NULL REFERENCES memory_summary_batches(batch_id), ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id), summary_version TEXT NOT NULL,
    PRIMARY KEY(batch_id, ordinal), UNIQUE(batch_id, segment_id)
);
CREATE TABLE conversation_digests (
    digest_id TEXT PRIMARY KEY NOT NULL, batch_id TEXT NOT NULL UNIQUE REFERENCES memory_summary_batches(batch_id),
    content TEXT NOT NULL CHECK(length(trim(content)) > 0), content_version TEXT NOT NULL,
    covers_through_sequence INTEGER NOT NULL CHECK(covers_through_sequence >= 1), created_at_utc TEXT NOT NULL
);
CREATE TABLE memory_organization_consumption (
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id), summary_version TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES memory_summary_batches(batch_id),
    outcome TEXT NOT NULL CHECK(outcome IN ('completed','no_op')), consumed_at_utc TEXT NOT NULL,
    PRIMARY KEY(segment_id, summary_version)
);
CREATE TABLE diary_entries (
    diary_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    game_day TEXT NOT NULL CHECK(date(game_day) IS NOT NULL AND date(game_day) = game_day),
    content TEXT NOT NULL, content_version TEXT NOT NULL, source_window_kind TEXT NOT NULL, source_window_ref TEXT NOT NULL,
    created_at_utc TEXT NOT NULL, UNIQUE(character_id, game_day),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id)
);
CREATE TABLE memory_views (
    community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    view_kind TEXT NOT NULL CHECK(view_kind IN ('core_memory','state_summary')),
    content TEXT NOT NULL, content_version TEXT NOT NULL,
    source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json)), source_snapshot_version TEXT, updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(character_id, view_kind),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id)
);

-- 记忆图和可重建全文投影
CREATE TABLE memory_entities (
    entity_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    entity_kind TEXT NOT NULL, canonical_name TEXT NOT NULL, created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL, invalidated_at_utc TEXT,
    UNIQUE(character_id, entity_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id)
);
CREATE TABLE memory_entity_aliases (
    alias_id TEXT PRIMARY KEY NOT NULL, character_id TEXT NOT NULL, entity_id TEXT NOT NULL,
    alias_text TEXT NOT NULL, normalized_alias TEXT NOT NULL, created_at_utc TEXT NOT NULL, invalidated_at_utc TEXT,
    FOREIGN KEY(character_id, entity_id) REFERENCES memory_entities(character_id, entity_id)
);
CREATE TABLE memory_entry_entities (
    character_id TEXT NOT NULL, memory_id TEXT NOT NULL, entity_id TEXT NOT NULL, role TEXT NOT NULL, created_at_utc TEXT NOT NULL,
    PRIMARY KEY(character_id, memory_id, entity_id, role),
    FOREIGN KEY(character_id, memory_id) REFERENCES memory_entries(character_id, memory_id),
    FOREIGN KEY(character_id, entity_id) REFERENCES memory_entities(character_id, entity_id)
);
CREATE TABLE memory_edges (
    edge_id TEXT PRIMARY KEY NOT NULL, character_id TEXT NOT NULL, from_entity_id TEXT NOT NULL, to_entity_id TEXT NOT NULL,
    edge_kind TEXT NOT NULL, confidence REAL NOT NULL DEFAULT 1.0 CHECK(confidence BETWEEN 0 AND 1), source_memory_id TEXT,
    created_at_utc TEXT NOT NULL, invalidated_at_utc TEXT,
    FOREIGN KEY(character_id, from_entity_id) REFERENCES memory_entities(character_id, entity_id),
    FOREIGN KEY(character_id, to_entity_id) REFERENCES memory_entities(character_id, entity_id),
    FOREIGN KEY(character_id, source_memory_id) REFERENCES memory_entries(character_id, memory_id),
    UNIQUE(character_id, from_entity_id, to_entity_id, edge_kind, source_memory_id)
);
CREATE TABLE memory_search_documents (
    document_id INTEGER PRIMARY KEY, community_id TEXT NOT NULL, character_id TEXT NOT NULL, conversation_id TEXT,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('memory_entry','message')), source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    occurred_at_utc TEXT, searchable INTEGER NOT NULL DEFAULT 1 CHECK(searchable IN (0,1)), updated_at_utc TEXT NOT NULL,
    UNIQUE(character_id, source_kind, source_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id)
);
CREATE VIRTUAL TABLE memory_search_fts USING fts5(tokenized_text, display_text UNINDEXED);

-- 已实现反思图的运行、节点、产物和审核
CREATE TABLE reflection_graph_runs (
    graph_run_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    graph_kind TEXT NOT NULL, graph_version TEXT NOT NULL, context_snapshot_id TEXT NOT NULL,
    snapshot_schema_version INTEGER NOT NULL DEFAULT 1 CHECK(snapshot_schema_version = 1),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)), snapshot_fingerprint TEXT NOT NULL,
    source_scope_json TEXT NOT NULL CHECK(json_valid(source_scope_json)), source_scope_fingerprint TEXT NOT NULL,
    topology_node_keys_json TEXT NOT NULL CHECK(json_valid(topology_node_keys_json)),
    required_node_keys_json TEXT NOT NULL CHECK(json_valid(required_node_keys_json)),
    registered_node_keys_json TEXT NOT NULL CHECK(json_valid(registered_node_keys_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','running','retry_wait','completed','partial','failed','cancelled')),
    execution_generation INTEGER NOT NULL DEFAULT 0 CHECK(execution_generation >= 0),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL, started_at_utc TEXT, completed_at_utc TEXT,
    last_error_code TEXT, trace_id TEXT,
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    UNIQUE(character_id, graph_kind, graph_version, context_snapshot_id, source_scope_fingerprint),
    CHECK((status IN ('completed','partial','failed','cancelled') AND completed_at_utc IS NOT NULL) OR
          (status IN ('pending','running','retry_wait') AND completed_at_utc IS NULL))
);
CREATE TABLE reflection_node_tasks (
    node_task_id TEXT PRIMARY KEY NOT NULL, graph_run_id TEXT NOT NULL REFERENCES reflection_graph_runs(graph_run_id),
    node_key TEXT NOT NULL, node_kind TEXT NOT NULL,
    dependency_keys_json TEXT NOT NULL CHECK(json_valid(dependency_keys_json)), activated INTEGER NOT NULL CHECK(activated IN (0,1)),
    node_input_fingerprint TEXT NOT NULL, input_artifact_refs_json TEXT NOT NULL CHECK(json_valid(input_artifact_refs_json)),
    output_contract_kind TEXT NOT NULL, output_contract_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending','processing','retry_wait','skipped','completed','failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0), lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0),
    available_at_utc TEXT NOT NULL, lease_owner TEXT, lease_until_utc TEXT, last_error_code TEXT,
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    UNIQUE(graph_run_id, node_key), UNIQUE(graph_run_id, node_task_id),
    CHECK((status = 'processing' AND lease_owner IS NOT NULL AND lease_until_utc IS NOT NULL) OR
          (status != 'processing' AND lease_owner IS NULL AND lease_until_utc IS NULL))
);
CREATE TABLE reflection_artifacts (
    artifact_id TEXT PRIMARY KEY NOT NULL, graph_run_id TEXT NOT NULL, node_task_id TEXT NOT NULL, invocation_id TEXT,
    attempt INTEGER NOT NULL CHECK(attempt >= 1), node_input_fingerprint TEXT NOT NULL,
    output_contract_kind TEXT NOT NULL, output_contract_version TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), content_fingerprint TEXT NOT NULL,
    evidence_refs_json TEXT NOT NULL CHECK(json_valid(evidence_refs_json)), audit_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(audit_json)),
    created_at_utc TEXT NOT NULL, UNIQUE(node_task_id, attempt),
    FOREIGN KEY(graph_run_id, node_task_id) REFERENCES reflection_node_tasks(graph_run_id, node_task_id)
);
CREATE TABLE reflection_graph_results (
    result_id TEXT PRIMARY KEY NOT NULL, graph_run_id TEXT NOT NULL UNIQUE REFERENCES reflection_graph_runs(graph_run_id),
    aggregate_fingerprint TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','approved','rejected','expired','skipped')),
    decision_code TEXT, created_at_utc TEXT NOT NULL, decided_at_utc TEXT,
    CHECK((status = 'pending' AND decision_code IS NULL AND decided_at_utc IS NULL) OR
          (status != 'pending' AND decision_code IS NOT NULL AND decided_at_utc IS NOT NULL))
);

-- 追踪投递不阻塞消息读取
CREATE TABLE trace_outbox (
    trace_id TEXT PRIMARY KEY NOT NULL, correlation_id TEXT NOT NULL, kind TEXT NOT NULL,
    entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), created_at_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending' CHECK(status IN ('pending','processing','failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0), available_at_utc TEXT NOT NULL,
    lease_owner TEXT, lease_until_utc TEXT, last_error_code TEXT,
    CHECK((status = 'processing' AND lease_owner IS NOT NULL AND lease_until_utc IS NOT NULL) OR
          (status != 'processing' AND lease_owner IS NULL AND lease_until_utc IS NULL))
);
CREATE TABLE traces (
    trace_id TEXT PRIMARY KEY NOT NULL, correlation_id TEXT NOT NULL, kind TEXT NOT NULL,
    entity_type TEXT NOT NULL, entity_id TEXT NOT NULL, payload_json TEXT NOT NULL CHECK(json_valid(payload_json)), created_at_utc TEXT NOT NULL
);

-- 实际读取和领取路径的索引
CREATE INDEX conversations_community ON conversations(community_id, created_at_utc, conversation_id);
CREATE UNIQUE INDEX memberships_current ON conversation_memberships(conversation_id, actor_kind, actor_id) WHERE left_at_utc IS NULL;
CREATE INDEX memberships_history ON conversation_memberships(conversation_id, actor_kind, actor_id, joined_after_sequence);
CREATE INDEX recipients_membership ON message_recipients(membership_id, message_id);
CREATE UNIQUE INDEX messages_client ON messages(sender_id, client_message_id) WHERE sender_kind = 'player';
CREATE UNIQUE INDEX batches_collecting ON input_batches(conversation_id, sender_kind, sender_id, visibility, audience_json) WHERE status = 'collecting';
CREATE INDEX batches_due ON input_batches(status, sender_kind, quiet_until_utc, created_at_utc);
CREATE UNIQUE INDEX turns_running ON social_turns(conversation_id) WHERE status = 'running';
CREATE INDEX tasks_claim ON conversation_tasks(status, available_at_utc, created_at_utc, task_id);
CREATE UNIQUE INDEX results_approved ON conversation_results(task_id) WHERE status = 'approved';
CREATE INDEX state_latest ON character_state_entries(character_id, state_kind, state_version DESC);
CREATE INDEX evidence_target ON relation_evidence(observer_character_id, target_kind, target_id, occurred_at_utc);
CREATE INDEX segments_order ON memory_segments(character_id, conversation_id, first_message_sequence);
CREATE INDEX segments_pending ON memory_segments(status, sealed_at_utc, segment_id);
CREATE INDEX memories_resident ON memory_entries(character_id, visibility, salience DESC, recorded_at_utc DESC) WHERE invalidated_at_utc IS NULL;
CREATE INDEX memories_source ON memory_entries(character_id, source_kind, source_ref);
CREATE INDEX thoughts_day ON thoughts(character_id, game_day, created_at_utc);
CREATE INDEX thoughts_segment ON thoughts(segment_id);
CREATE INDEX coverage_source ON memory_source_coverage(character_id, source_kind, source_id);
CREATE UNIQUE INDEX aliases_active ON memory_entity_aliases(character_id, normalized_alias) WHERE invalidated_at_utc IS NULL;
CREATE INDEX entries_entity ON memory_entry_entities(character_id, entity_id, memory_id);
CREATE UNIQUE INDEX edges_without_source ON memory_edges(character_id, from_entity_id, to_entity_id, edge_kind) WHERE source_memory_id IS NULL;
CREATE INDEX edges_from ON memory_edges(character_id, from_entity_id) WHERE invalidated_at_utc IS NULL;
CREATE INDEX edges_to ON memory_edges(character_id, to_entity_id) WHERE invalidated_at_utc IS NULL;
CREATE INDEX search_scope ON memory_search_documents(character_id, searchable, source_kind);
CREATE INDEX graphs_recovery ON reflection_graph_runs(status, updated_at_utc, graph_run_id);
CREATE INDEX nodes_claim ON reflection_node_tasks(status, available_at_utc, created_at_utc);
CREATE INDEX nodes_graph ON reflection_node_tasks(graph_run_id, status, activated, available_at_utc);
CREATE INDEX artifacts_graph ON reflection_artifacts(graph_run_id, created_at_utc, artifact_id);
CREATE INDEX outbox_claim ON trace_outbox(status, available_at_utc, created_at_utc);
CREATE INDEX traces_correlation ON traces(correlation_id, created_at_utc, trace_id);
