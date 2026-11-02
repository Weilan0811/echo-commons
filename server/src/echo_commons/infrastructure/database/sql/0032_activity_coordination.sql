CREATE TABLE activity_tasks_coordinated (
    task_id TEXT PRIMARY KEY,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    game_id TEXT NOT NULL REFERENCES community_games(game_id),
    participation_id TEXT NOT NULL REFERENCES game_participations(participation_id),
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    membership_id TEXT NOT NULL REFERENCES conversation_memberships(membership_id),
    opportunity_id TEXT,
    state_version INTEGER NOT NULL,
    view_json TEXT CHECK(view_json IS NULL OR json_valid(view_json)),
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
    purpose TEXT NOT NULL CHECK(purpose IN ('turn','reply')),
    CHECK((purpose='turn' AND opportunity_id IS NOT NULL AND view_json IS NOT NULL)
        OR (purpose='reply' AND opportunity_id IS NULL AND mode!='automatic'))
);
INSERT INTO activity_tasks_coordinated SELECT *, 'turn' FROM activity_tasks;
DROP TABLE activity_tasks;
ALTER TABLE activity_tasks_coordinated RENAME TO activity_tasks;
CREATE INDEX activity_tasks_claim ON activity_tasks(status,available_at_utc);
CREATE UNIQUE INDEX activity_opportunity ON activity_tasks(game_id,participation_id,opportunity_id)
    WHERE purpose='turn' AND status NOT IN ('failed','cancelled');

CREATE TABLE activity_results_coordinated (
    result_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL UNIQUE REFERENCES activity_tasks(task_id),
    execution_mode TEXT NOT NULL CHECK(execution_mode IN ('automatic','decision','ordinary','decision_then_ordinary')),
    artifact_json TEXT NOT NULL CHECK(json_valid(artifact_json)),
    receipt_json TEXT CHECK(receipt_json IS NULL OR json_valid(receipt_json)),
    expression_json TEXT CHECK(expression_json IS NULL OR json_valid(expression_json)),
    expression_status TEXT NOT NULL CHECK(expression_status IN ('silent','pending_generation','pending_review')),
    created_at_utc TEXT NOT NULL
);
INSERT INTO activity_results_coordinated SELECT * FROM activity_results;
DROP TABLE activity_results;
ALTER TABLE activity_results_coordinated RENAME TO activity_results;

CREATE TABLE activity_task_sources (
    source_id TEXT PRIMARY KEY NOT NULL,
    social_turn_id TEXT NOT NULL REFERENCES social_turns(social_turn_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    membership_id TEXT NOT NULL REFERENCES conversation_memberships(membership_id),
    task_id TEXT REFERENCES activity_tasks(task_id),
    observation_max_sequence INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN
        ('reserved','queued','attached','frozen','silent','pending_expression','failed','cancelled')),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE(social_turn_id,character_id)
);
CREATE INDEX activity_sources_task ON activity_task_sources(task_id,status);

CREATE TABLE participation_decisions_activity (
    social_turn_id TEXT NOT NULL REFERENCES social_turns(social_turn_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    reason_code TEXT NOT NULL, selection_order INTEGER CHECK(selection_order>=0),
    status TEXT NOT NULL CHECK(status IN ('silent','selected','completed','failed','cancelled')),
    outcome TEXT, updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(social_turn_id,character_id),
    CHECK((status='selected' AND outcome IS NULL)
       OR (status!='selected' AND outcome IS NOT NULL)),
    CHECK((status='silent' AND selection_order IS NULL AND outcome='silent') OR
          (status='selected' AND selection_order IS NOT NULL AND outcome IS NULL) OR
          (status='completed' AND selection_order IS NOT NULL AND
           outcome IN ('message','silent','pending_expression')) OR
          (status='failed' AND selection_order IS NOT NULL AND outcome='failed') OR
          (status='cancelled' AND selection_order IS NOT NULL AND outcome='cancelled'))
);
INSERT INTO participation_decisions_activity SELECT * FROM participation_decisions;
DROP TABLE participation_decisions;
ALTER TABLE participation_decisions_activity RENAME TO participation_decisions;

-- 旧版本通常只有一个行动机会；保留最新安排，来源历史继续保留。
UPDATE activity_tasks AS t SET status='cancelled',lease_owner=NULL,lease_until_utc=NULL,
    lease_generation=lease_generation+1,last_error_code='coordination_replaced'
WHERE status IN ('pending','processing','retry_wait','suspended') AND EXISTS (
    SELECT 1 FROM activity_tasks newer WHERE newer.game_id=t.game_id
    AND newer.participation_id=t.participation_id
    AND newer.status IN ('pending','processing','retry_wait','suspended')
    AND (newer.created_at_utc,newer.task_id)>(t.created_at_utc,t.task_id)
);
CREATE UNIQUE INDEX activity_active_participation ON activity_tasks(game_id,participation_id)
    WHERE status IN ('pending','processing','retry_wait','suspended');
