CREATE TABLE IF NOT EXISTS meta (
    key TEXT PRIMARY KEY,
    value TEXT NOT NULL
);

INSERT INTO meta(key, value)
VALUES ('state_version', '0'), ('database_created_at_utc', strftime('%Y-%m-%dT%H:%M:%fZ', 'now')),
       ('last_successful_start_version', '')
ON CONFLICT(key) DO NOTHING;

CREATE TABLE IF NOT EXISTS conversations (
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    stage_summary TEXT NOT NULL DEFAULT '',
    context_version TEXT NOT NULL DEFAULT '0',
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY (account_id, conversation_id)
);

CREATE TABLE IF NOT EXISTS messages (
    message_sequence INTEGER PRIMARY KEY AUTOINCREMENT,
    message_id TEXT NOT NULL UNIQUE,
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    sender_type TEXT NOT NULL CHECK(sender_type IN ('player', 'character', 'system')),
    sender_id TEXT NOT NULL,
    text TEXT NOT NULL,
    images_json TEXT NOT NULL,
    client_msg_id TEXT,
    normalized_payload_hash TEXT,
    client_timestamp_utc TEXT,
    server_timestamp_utc TEXT NOT NULL,
    reply_to_message_id TEXT,
    trace_id TEXT NOT NULL
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_account_client_msg
ON messages(account_id, client_msg_id) WHERE client_msg_id IS NOT NULL;
CREATE INDEX IF NOT EXISTS ix_messages_account_sequence ON messages(account_id, message_sequence);
CREATE INDEX IF NOT EXISTS ix_messages_conversation_sequence
ON messages(account_id, conversation_id, message_sequence);
CREATE UNIQUE INDEX IF NOT EXISTS uq_character_reply_to_message
ON messages(reply_to_message_id)
WHERE sender_type = 'character' AND reply_to_message_id IS NOT NULL;

CREATE TABLE IF NOT EXISTS conversation_turns (
    turn_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    trigger_message_id TEXT NOT NULL UNIQUE REFERENCES messages(message_id),
    status TEXT NOT NULL CHECK(status IN ('pending', 'processing', 'retry_wait', 'completed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0,
    available_at_utc TEXT NOT NULL,
    lease_owner TEXT,
    lease_until_utc TEXT,
    last_error_code TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    trace_id TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_turns_claim ON conversation_turns(status, available_at_utc, created_at_utc);

CREATE TABLE IF NOT EXISTS situation_proposals (
    proposal_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL REFERENCES conversation_turns(turn_id),
    agent_id TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected', 'expired')),
    utterance TEXT NOT NULL,
    actions_json TEXT NOT NULL,
    context_version TEXT NOT NULL,
    decision_code TEXT,
    created_at_utc TEXT NOT NULL,
    decided_at_utc TEXT
);
CREATE UNIQUE INDEX IF NOT EXISTS uq_approved_proposal_turn
ON situation_proposals(turn_id) WHERE status = 'approved';

CREATE TABLE IF NOT EXISTS traces (
    trace_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE INDEX IF NOT EXISTS ix_traces_correlation ON traces(correlation_id, created_at_utc);
