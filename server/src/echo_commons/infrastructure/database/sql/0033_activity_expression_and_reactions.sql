CREATE TABLE messages_activity (
    message_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    sequence INTEGER NOT NULL CHECK(sequence>=1),
    sender_kind TEXT NOT NULL CHECK(sender_kind IN ('player','character','system')), sender_id TEXT NOT NULL,
    sender_membership_id TEXT, text TEXT NOT NULL CHECK(length(trim(text))>0),
    visibility TEXT NOT NULL CHECK(visibility IN ('conversation','recipients')),
    reply_to_message_id TEXT, client_message_id TEXT,
    source_turn_id TEXT, result_id TEXT UNIQUE REFERENCES conversation_results(result_id),
    trace_id TEXT NOT NULL, created_at_utc TEXT NOT NULL,
    activity_result_id TEXT UNIQUE REFERENCES activity_results(result_id),
    UNIQUE(conversation_id,sequence), UNIQUE(conversation_id,message_id),
    FOREIGN KEY(community_id,conversation_id) REFERENCES conversations(community_id,conversation_id),
    FOREIGN KEY(conversation_id,sender_membership_id) REFERENCES conversation_memberships(conversation_id,membership_id),
    FOREIGN KEY(conversation_id,reply_to_message_id) REFERENCES messages(conversation_id,message_id),
    FOREIGN KEY(community_id,conversation_id,source_turn_id) REFERENCES social_turns(community_id,conversation_id,social_turn_id),
    CHECK((sender_kind='system' AND sender_membership_id IS NULL) OR
          (sender_kind!='system' AND sender_membership_id IS NOT NULL)),
    CHECK(sender_kind!='player' OR (client_message_id IS NOT NULL AND result_id IS NULL AND activity_result_id IS NULL AND source_turn_id IS NULL)),
    CHECK(sender_kind!='character' OR (source_turn_id IS NOT NULL AND client_message_id IS NULL
          AND ((result_id IS NOT NULL AND activity_result_id IS NULL) OR (result_id IS NULL AND activity_result_id IS NOT NULL)))),
    CHECK(sender_kind='player' OR client_message_id IS NULL)
);
INSERT INTO messages_activity SELECT *,NULL FROM messages;
DROP TABLE messages;
ALTER TABLE messages_activity RENAME TO messages;
CREATE UNIQUE INDEX messages_client ON messages(sender_id,client_message_id) WHERE sender_kind='player';

ALTER TABLE activity_results ADD COLUMN publication_status TEXT NOT NULL DEFAULT 'pending'
    CHECK(publication_status IN ('pending','published','silent','rejected','failed','cancelled'));
UPDATE activity_results SET publication_status='silent' WHERE expression_status='silent';

CREATE TABLE activity_expression_tasks (
    task_id TEXT PRIMARY KEY REFERENCES activity_results(result_id),
    status TEXT NOT NULL CHECK(status IN ('pending','processing','retry_wait','suspended','completed','failed','cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0, lease_generation INTEGER NOT NULL DEFAULT 0,
    lease_owner TEXT, lease_until_utc TEXT, available_at_utc TEXT NOT NULL,
    last_error_code TEXT, created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    input_json TEXT CHECK(input_json IS NULL OR json_valid(input_json)),
    last_invocation_json TEXT CHECK(last_invocation_json IS NULL OR json_valid(last_invocation_json)),
    last_run_json TEXT CHECK(last_run_json IS NULL OR json_valid(last_run_json)),
    prepared_json TEXT CHECK(prepared_json IS NULL OR json_valid(prepared_json)),
    social_turn_id TEXT REFERENCES social_turns(social_turn_id)
);
INSERT INTO activity_expression_tasks(task_id,status,available_at_utc,created_at_utc,updated_at_utc)
    SELECT result_id,'pending',created_at_utc,created_at_utc,created_at_utc FROM activity_results
    WHERE expression_status!='silent';

CREATE TABLE activity_sources_published (
    source_id TEXT PRIMARY KEY NOT NULL,
    social_turn_id TEXT NOT NULL REFERENCES social_turns(social_turn_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    membership_id TEXT NOT NULL REFERENCES conversation_memberships(membership_id),
    task_id TEXT REFERENCES activity_tasks(task_id), observation_max_sequence INTEGER NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('reserved','queued','attached','frozen','silent','pending_expression','published','failed','cancelled')),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    UNIQUE(social_turn_id,character_id)
);
INSERT INTO activity_sources_published SELECT * FROM activity_task_sources;
DROP TABLE activity_task_sources;
ALTER TABLE activity_sources_published RENAME TO activity_task_sources;
CREATE INDEX activity_sources_task ON activity_task_sources(task_id,status);

CREATE TABLE activity_reaction_opportunities (
    opportunity_id TEXT PRIMARY KEY,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    game_id TEXT NOT NULL REFERENCES community_games(game_id),
    kind TEXT NOT NULL CHECK(kind IN ('events','quiet','settlement')),
    after_sequence INTEGER NOT NULL,
    through_sequence INTEGER NOT NULL, boundary_utc TEXT NOT NULL,
    event_ids_json TEXT NOT NULL CHECK(json_valid(event_ids_json)),
    visible_event_ids_json TEXT CHECK(visible_event_ids_json IS NULL OR json_valid(visible_event_ids_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','skipped','arranged','cancelled')),
    probability REAL, sample REAL, character_id TEXT,
    source_id TEXT REFERENCES activity_task_sources(source_id),
    created_at_utc TEXT NOT NULL,
    UNIQUE(game_id,kind,through_sequence,boundary_utc)
);
CREATE TABLE activity_reaction_clocks (
    game_id TEXT PRIMARY KEY REFERENCES community_games(game_id),
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    last_scanned_at_utc TEXT NOT NULL, message_sequence INTEGER NOT NULL,
    state_version INTEGER NOT NULL, quiet_seconds REAL NOT NULL, since_message_seconds REAL NOT NULL,
    quiet_done INTEGER NOT NULL DEFAULT 0
);
CREATE TABLE activity_event_coverage (
    result_id TEXT NOT NULL REFERENCES activity_results(result_id),
    event_id TEXT NOT NULL,
    PRIMARY KEY(result_id,event_id)
);
