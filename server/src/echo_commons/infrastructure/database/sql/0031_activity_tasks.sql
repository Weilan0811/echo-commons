CREATE TABLE activity_tasks (
    task_id TEXT PRIMARY KEY,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    game_id TEXT NOT NULL REFERENCES community_games(game_id),
    participation_id TEXT NOT NULL REFERENCES game_participations(participation_id),
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    membership_id TEXT NOT NULL REFERENCES conversation_memberships(membership_id),
    opportunity_id TEXT NOT NULL,
    state_version INTEGER NOT NULL,
    view_json TEXT NOT NULL CHECK(json_valid(view_json)),
    input_id TEXT NOT NULL UNIQUE,
    request_id TEXT NOT NULL UNIQUE,
    mode TEXT NOT NULL CHECK(mode IN ('automatic','decision','ordinary')),
    model_profile TEXT NOT NULL,
    decision_request_json TEXT CHECK(decision_request_json IS NULL OR json_valid(decision_request_json)),
    decision_response_json TEXT CHECK(decision_response_json IS NULL OR json_valid(decision_response_json)),
    prepared_json TEXT CHECK(prepared_json IS NULL OR json_valid(prepared_json)),
    last_invocation_json TEXT CHECK(last_invocation_json IS NULL OR json_valid(last_invocation_json)),
    last_run_json TEXT CHECK(last_run_json IS NULL OR json_valid(last_run_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','processing','retry_wait','suspended','completed','failed','cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    lease_generation INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT,
    lease_until_utc TEXT,
    available_at_utc TEXT NOT NULL,
    last_error_code TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    UNIQUE(game_id,participation_id,opportunity_id)
);
CREATE INDEX activity_tasks_claim ON activity_tasks(status,available_at_utc);

CREATE TABLE activity_results (
    result_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE REFERENCES activity_tasks(task_id),
    execution_mode TEXT NOT NULL CHECK(execution_mode IN ('automatic','decision','ordinary','decision_then_ordinary')),
    artifact_json TEXT NOT NULL CHECK(json_valid(artifact_json)),
    receipt_json TEXT NOT NULL CHECK(json_valid(receipt_json)),
    expression_json TEXT CHECK(expression_json IS NULL OR json_valid(expression_json)),
    expression_status TEXT NOT NULL CHECK(expression_status IN ('silent','pending_generation','pending_review')),
    created_at_utc TEXT NOT NULL
);

CREATE TABLE thoughts_activity (
    thought_id TEXT PRIMARY KEY NOT NULL,
    result_id TEXT UNIQUE REFERENCES conversation_results(result_id),
    community_id TEXT NOT NULL, character_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    game_day TEXT NOT NULL CHECK(date(game_day) IS NOT NULL AND date(game_day)=game_day),
    content TEXT, content_version TEXT NOT NULL, segment_id TEXT,
    created_at_utc TEXT NOT NULL, content_removed_at_utc TEXT,
    activity_result_id TEXT UNIQUE REFERENCES activity_results(result_id),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id),
    FOREIGN KEY(community_id,conversation_id) REFERENCES conversations(community_id,conversation_id),
    FOREIGN KEY(character_id,segment_id) REFERENCES memory_segments(character_id,segment_id),
    CHECK((result_id IS NULL) != (activity_result_id IS NULL)),
    CHECK((content IS NOT NULL AND length(trim(content))>0 AND content_removed_at_utc IS NULL) OR
          (content IS NULL AND content_removed_at_utc IS NOT NULL AND content_removed_at_utc>=created_at_utc))
);
INSERT INTO thoughts_activity (
    thought_id,result_id,community_id,character_id,conversation_id,game_day,content,
    content_version,segment_id,created_at_utc,content_removed_at_utc
) SELECT thought_id,result_id,community_id,character_id,conversation_id,game_day,content,
    content_version,segment_id,created_at_utc,content_removed_at_utc FROM thoughts;
DROP TABLE thoughts;
ALTER TABLE thoughts_activity RENAME TO thoughts;
CREATE INDEX thoughts_day ON thoughts(character_id,game_day,created_at_utc);
CREATE INDEX thoughts_segment ON thoughts(segment_id);
