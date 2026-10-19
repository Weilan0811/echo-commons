UPDATE conversation_tasks SET status='cancelled',lease_owner=NULL,lease_until_utc=NULL,
    lease_generation=lease_generation+1,last_error_code='scheduling_changed'
WHERE status IN ('pending','processing','retry_wait','suspended');
UPDATE participation_decisions SET status='cancelled',outcome='cancelled'
WHERE status='selected';
UPDATE social_turns AS s SET status='cancelled',completion_json=(
    SELECT json_group_object(outcome,total) FROM (
        SELECT outcome,COUNT(*) AS total FROM participation_decisions p
        WHERE p.social_turn_id=s.social_turn_id GROUP BY outcome
    )
),
    completed_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),stop_reason='scheduling_changed'
WHERE status IN ('pending','running');
UPDATE social_chains SET status='cancelled',stop_reason='scheduling_changed',
    completed_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now') WHERE status='active';

CREATE TABLE social_chains_new (
    chain_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    max_messages INTEGER NOT NULL CHECK(max_messages>0),
    max_tasks INTEGER NOT NULL CHECK(max_tasks>0),
    message_count INTEGER NOT NULL DEFAULT 0 CHECK(message_count>=0 AND message_count<=max_messages),
    task_count INTEGER NOT NULL DEFAULT 0 CHECK(task_count>=0 AND task_count<=max_tasks),
    status TEXT NOT NULL CHECK(status IN ('active','completed','cancelled')),
    stop_reason TEXT, created_at_utc TEXT NOT NULL, completed_at_utc TEXT,
    FOREIGN KEY(community_id,conversation_id) REFERENCES conversations(community_id,conversation_id),
    UNIQUE(community_id,conversation_id,chain_id),
    CHECK((status='active' AND stop_reason IS NULL AND completed_at_utc IS NULL)
       OR (status!='active' AND stop_reason IS NOT NULL AND completed_at_utc IS NOT NULL))
);
INSERT INTO social_chains_new SELECT chain_id,community_id,conversation_id,max_messages,max_tasks,
    message_count,task_count,status,stop_reason,created_at_utc,completed_at_utc FROM social_chains;
DROP TABLE social_chains;
ALTER TABLE social_chains_new RENAME TO social_chains;
CREATE UNIQUE INDEX chains_active ON social_chains(conversation_id) WHERE status='active';

DROP TABLE social_triggers;
DROP TABLE social_candidates;
ALTER TABLE social_turns DROP COLUMN parent_turn_id;
ALTER TABLE social_turns DROP COLUMN depth;

CREATE TABLE social_chain_batches (
    chain_id TEXT NOT NULL REFERENCES social_chains(chain_id),
    input_batch_id TEXT PRIMARY KEY NOT NULL REFERENCES input_batches(input_batch_id)
);
INSERT INTO social_chain_batches
SELECT DISTINCT s.chain_id,b.input_batch_id FROM social_turn_batches b
JOIN social_turns s USING(social_turn_id) WHERE s.chain_id IS NOT NULL;
INSERT OR IGNORE INTO social_chain_batches
SELECT s.chain_id,b.input_batch_id FROM input_batches b
JOIN social_turns s ON s.social_turn_id=b.origin_turn_id WHERE s.chain_id IS NOT NULL;

CREATE TABLE social_observations (
    chain_id TEXT NOT NULL REFERENCES social_chains(chain_id),
    membership_id TEXT NOT NULL REFERENCES conversation_memberships(membership_id),
    considered_through_sequence INTEGER NOT NULL CHECK(considered_through_sequence>=0),
    PRIMARY KEY(chain_id,membership_id)
);

CREATE TABLE social_turn_batches_new (
    social_turn_id TEXT NOT NULL REFERENCES social_turns(social_turn_id),
    input_batch_id TEXT NOT NULL REFERENCES input_batches(input_batch_id),
    ordinal INTEGER NOT NULL CHECK(ordinal>=0),
    PRIMARY KEY(social_turn_id,input_batch_id), UNIQUE(social_turn_id,ordinal)
);
INSERT INTO social_turn_batches_new SELECT * FROM social_turn_batches;
DROP TABLE social_turn_batches;
ALTER TABLE social_turn_batches_new RENAME TO social_turn_batches;

CREATE TABLE conversation_tasks_new (
    task_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    social_turn_id TEXT NOT NULL, character_id TEXT NOT NULL, membership_id TEXT NOT NULL,
    snapshot_id TEXT UNIQUE,
    snapshot_schema_version INTEGER CHECK(snapshot_schema_version=2),
    snapshot_json TEXT CHECK(snapshot_json IS NULL OR json_valid(snapshot_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','processing','retry_wait','suspended','completed','failed','cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation>=0),
    available_at_utc TEXT NOT NULL, lease_owner TEXT, lease_until_utc TEXT, last_error_code TEXT,
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL, trace_id TEXT NOT NULL,
    UNIQUE(social_turn_id,character_id),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id),
    FOREIGN KEY(community_id,conversation_id,social_turn_id) REFERENCES social_turns(community_id,conversation_id,social_turn_id),
    FOREIGN KEY(social_turn_id,character_id) REFERENCES participation_decisions(social_turn_id,character_id),
    FOREIGN KEY(community_id,conversation_id,membership_id) REFERENCES conversation_memberships(community_id,conversation_id,membership_id),
    CHECK((snapshot_id IS NULL AND snapshot_json IS NULL AND snapshot_schema_version IS NULL
           AND status IN ('pending','suspended','cancelled'))
       OR (snapshot_id IS NOT NULL AND snapshot_json IS NOT NULL AND snapshot_schema_version IS NOT NULL)),
    CHECK((status='processing' AND lease_owner IS NOT NULL AND lease_until_utc IS NOT NULL)
       OR (status!='processing' AND lease_owner IS NULL AND lease_until_utc IS NULL))
);
INSERT INTO conversation_tasks_new SELECT task_id,community_id,conversation_id,social_turn_id,
    character_id,membership_id,snapshot_id,snapshot_schema_version,
    json_remove(snapshot_json,'$.perspective.root_message_ids'),status,attempt_count,lease_generation,
    available_at_utc,lease_owner,lease_until_utc,last_error_code,created_at_utc,updated_at_utc,trace_id
FROM conversation_tasks;
DROP TABLE conversation_tasks;
ALTER TABLE conversation_tasks_new RENAME TO conversation_tasks;
CREATE INDEX tasks_claim ON conversation_tasks(status,available_at_utc,created_at_utc,task_id);
