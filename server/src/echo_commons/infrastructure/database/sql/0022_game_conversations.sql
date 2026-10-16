CREATE TABLE conversations_new (
    conversation_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    kind TEXT NOT NULL CHECK(kind IN ('direct','group','game')),
    status TEXT NOT NULL DEFAULT 'active' CHECK(status IN ('active','archived')),
    membership_version INTEGER NOT NULL DEFAULT 0 CHECK(membership_version >= 0),
    next_sequence INTEGER NOT NULL DEFAULT 1 CHECK(next_sequence >= 1),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    state_version INTEGER NOT NULL DEFAULT 1 CHECK(state_version >= 1),
    creator_player_id TEXT REFERENCES players(player_id),
    legacy_small_group INTEGER NOT NULL DEFAULT 0 CHECK(legacy_small_group IN (0,1)),
    UNIQUE(community_id, conversation_id)
);
INSERT INTO conversations_new SELECT * FROM conversations;
DROP TABLE conversations;
ALTER TABLE conversations_new RENAME TO conversations;
CREATE INDEX conversations_community ON conversations(community_id, created_at_utc, conversation_id);

CREATE TABLE game_session_operations (
    operation_scope TEXT NOT NULL,
    requester_ref TEXT NOT NULL,
    request_id TEXT NOT NULL,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    game_id TEXT NOT NULL REFERENCES community_games(game_id),
    operation TEXT NOT NULL CHECK(operation IN ('create','join','leave','start','resign','cancel','end')),
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    result_json TEXT NOT NULL CHECK(json_valid(result_json)),
    PRIMARY KEY(operation_scope, requester_ref, request_id)
);
CREATE INDEX game_session_operations_game ON game_session_operations(game_id);
