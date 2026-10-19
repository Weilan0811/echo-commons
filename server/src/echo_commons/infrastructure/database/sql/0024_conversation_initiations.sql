CREATE TABLE conversation_initiations (
    initiation_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    request_id TEXT NOT NULL CHECK(length(trim(request_id)) > 0),
    situation TEXT NOT NULL CHECK(length(trim(situation)) > 0),
    audience_json TEXT NOT NULL CHECK(json_valid(audience_json)),
    created_at_utc TEXT NOT NULL,
    UNIQUE(community_id, request_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id)
);

CREATE TABLE social_turns_new (
    social_turn_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    audience_json TEXT NOT NULL CHECK(json_valid(audience_json) AND json_type(audience_json)='array'),
    visibility TEXT NOT NULL CHECK(visibility IN ('conversation','recipients')),
    observation_max_sequence INTEGER NOT NULL CHECK(observation_max_sequence>=0),
    membership_version INTEGER NOT NULL CHECK(membership_version>=0),
    status TEXT NOT NULL CHECK(status IN ('pending','running','completed','cancelled')),
    completion_json TEXT CHECK(completion_json IS NULL OR json_valid(completion_json)),
    created_at_utc TEXT NOT NULL, completed_at_utc TEXT,
    chain_id TEXT REFERENCES social_chains(chain_id),
    parent_turn_id TEXT REFERENCES social_turns(social_turn_id),
    depth INTEGER NOT NULL DEFAULT 0 CHECK(depth>=0),
    policy_version TEXT, stop_reason TEXT,
    initiation_id TEXT REFERENCES conversation_initiations(initiation_id),
    FOREIGN KEY(community_id,conversation_id) REFERENCES conversations(community_id,conversation_id),
    UNIQUE(community_id,conversation_id,social_turn_id),
    CHECK((status IN ('completed','cancelled') AND completed_at_utc IS NOT NULL AND completion_json IS NOT NULL)
       OR (status IN ('pending','running') AND completed_at_utc IS NULL AND completion_json IS NULL))
);
INSERT INTO social_turns_new (
    social_turn_id,community_id,conversation_id,audience_json,visibility,observation_max_sequence,
    membership_version,status,completion_json,created_at_utc,completed_at_utc,chain_id,parent_turn_id,
    depth,policy_version,stop_reason
)
SELECT social_turn_id,community_id,conversation_id,audience_json,visibility,observation_max_sequence,
    membership_version,status,completion_json,created_at_utc,completed_at_utc,chain_id,parent_turn_id,
    depth,policy_version,stop_reason FROM social_turns;
DROP TABLE social_turns;
ALTER TABLE social_turns_new RENAME TO social_turns;
CREATE UNIQUE INDEX turns_running ON social_turns(conversation_id) WHERE status='running';
CREATE UNIQUE INDEX turns_initiation ON social_turns(initiation_id) WHERE initiation_id IS NOT NULL;
