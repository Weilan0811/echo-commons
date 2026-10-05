CREATE TABLE conversation_read_positions (
    player_id TEXT NOT NULL REFERENCES players(player_id),
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    last_read_sequence INTEGER NOT NULL CHECK (last_read_sequence >= 0),
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (player_id, conversation_id)
);

CREATE TABLE conversation_membership_operations (
    operation_scope TEXT NOT NULL,
    client_operation_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    request_json TEXT NOT NULL,
    result_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY (operation_scope, client_operation_id)
);

CREATE INDEX idx_membership_operations_conversation
ON conversation_membership_operations(conversation_id);
