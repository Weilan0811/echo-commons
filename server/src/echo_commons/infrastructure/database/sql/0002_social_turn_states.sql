CREATE TABLE social_turns_updated (
    social_turn_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    audience_json TEXT NOT NULL CHECK(json_valid(audience_json) AND json_type(audience_json) = 'array'),
    visibility TEXT NOT NULL CHECK(visibility IN ('conversation','recipients')),
    observation_max_sequence INTEGER NOT NULL CHECK(observation_max_sequence >= 0),
    membership_version INTEGER NOT NULL CHECK(membership_version >= 0),
    status TEXT NOT NULL CHECK(status IN ('running','completed','cancelled')),
    completion_json TEXT CHECK(completion_json IS NULL OR json_valid(completion_json)),
    created_at_utc TEXT NOT NULL, completed_at_utc TEXT,
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    UNIQUE(community_id, conversation_id, social_turn_id),
    CHECK((status IN ('completed','cancelled') AND completed_at_utc IS NOT NULL AND completion_json IS NOT NULL)
       OR (status = 'running' AND completed_at_utc IS NULL AND completion_json IS NULL))
);
INSERT INTO social_turns_updated SELECT * FROM social_turns;
DROP TABLE social_turns;
ALTER TABLE social_turns_updated RENAME TO social_turns;
CREATE UNIQUE INDEX turns_running ON social_turns(conversation_id) WHERE status = 'running';
