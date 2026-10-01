-- S2.5 persistence foundation.  Existing M0 tables remain readable during
-- the cutover; the new Runtime path uses the tables below exclusively.
--
-- This migration changes the schema only.  Local M0 records are test data and
-- are deliberately not interpreted as new Runtime entities here.  Development
-- scenarios are created explicitly by tools/dev/echo_runtime_data.py.

ALTER TABLE conversations
ADD COLUMN kind TEXT NOT NULL DEFAULT 'direct'
CHECK(kind IN ('direct', 'group'));

ALTER TABLE conversations
ADD COLUMN status TEXT NOT NULL DEFAULT 'active'
CHECK(status IN ('active', 'archived'));

CREATE TABLE IF NOT EXISTS world_state (
    singleton_id INTEGER PRIMARY KEY CHECK(singleton_id = 1),
    state_version INTEGER NOT NULL CHECK(state_version >= 0),
    world_time_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('active', 'paused')),
    phase TEXT NOT NULL DEFAULT '',
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS character_states (
    character_id TEXT PRIMARY KEY CHECK(length(trim(character_id)) > 0),
    availability_status TEXT NOT NULL
        CHECK(availability_status IN (
            'available', 'offline', 'busy', 'story_absent', 'technical_error'
        )),
    reason_code TEXT,
    next_check_at_utc TEXT,
    state_version INTEGER NOT NULL CHECK(state_version >= 0),
    updated_at_utc TEXT NOT NULL
);

CREATE TABLE IF NOT EXISTS conversation_participants (
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    joined_at_utc TEXT NOT NULL,
    left_at_utc TEXT,
    PRIMARY KEY(account_id, conversation_id, character_id),
    FOREIGN KEY(account_id, conversation_id)
        REFERENCES conversations(account_id, conversation_id),
    FOREIGN KEY(character_id) REFERENCES character_states(character_id),
    CHECK(left_at_utc IS NULL OR left_at_utc >= joined_at_utc)
);

CREATE TABLE IF NOT EXISTS conversation_tasks (
    task_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN ('pending', 'processing', 'retry_wait', 'deferred', 'completed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    available_at_utc TEXT NOT NULL,
    lease_owner TEXT,
    lease_until_utc TEXT,
    input_max_message_sequence INTEGER NOT NULL CHECK(input_max_message_sequence > 0),
    context_max_message_sequence INTEGER NOT NULL
        CHECK(context_max_message_sequence >= input_max_message_sequence),
    world_state_version INTEGER NOT NULL CHECK(world_state_version >= 0),
    character_state_version INTEGER NOT NULL CHECK(character_state_version >= 0),
    context_version TEXT NOT NULL,
    last_error_code TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    trace_id TEXT NOT NULL,
    FOREIGN KEY(account_id, conversation_id)
        REFERENCES conversations(account_id, conversation_id),
    FOREIGN KEY(character_id) REFERENCES character_states(character_id),
    CHECK(
        (status = 'processing' AND lease_owner IS NOT NULL AND lease_until_utc IS NOT NULL)
        OR (status <> 'processing' AND lease_owner IS NULL AND lease_until_utc IS NULL)
    )
);

-- One active logical task per conversation.  Terminal tasks remain queryable.
CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_active_task
ON conversation_tasks(account_id, conversation_id)
WHERE status IN ('pending', 'processing', 'retry_wait', 'deferred');

CREATE INDEX IF NOT EXISTS ix_conversation_tasks_claim
ON conversation_tasks(status, available_at_utc, created_at_utc);

CREATE TABLE IF NOT EXISTS input_batches (
    input_batch_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    status TEXT NOT NULL
        CHECK(status IN ('collecting', 'waiting', 'assigned', 'covered', 'terminal_failed')),
    quiet_until_utc TEXT NOT NULL,
    sealed_at_utc TEXT,
    task_id TEXT,
    first_message_sequence INTEGER,
    last_message_sequence INTEGER,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    FOREIGN KEY(account_id, conversation_id)
        REFERENCES conversations(account_id, conversation_id),
    FOREIGN KEY(task_id) REFERENCES conversation_tasks(task_id),
    CHECK(
        (first_message_sequence IS NULL AND last_message_sequence IS NULL)
        OR (
            first_message_sequence IS NOT NULL
            AND last_message_sequence IS NOT NULL
            AND first_message_sequence > 0
            AND last_message_sequence >= first_message_sequence
        )
    ),
    CHECK(
        (status = 'collecting' AND sealed_at_utc IS NULL AND task_id IS NULL)
        OR (status = 'waiting' AND sealed_at_utc IS NOT NULL AND task_id IS NULL)
        OR (
            status IN ('assigned', 'covered', 'terminal_failed')
            AND sealed_at_utc IS NOT NULL
            AND task_id IS NOT NULL
        )
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_conversation_collecting_batch
ON input_batches(account_id, conversation_id)
WHERE status = 'collecting';

CREATE INDEX IF NOT EXISTS ix_input_batches_waiting
ON input_batches(status, quiet_until_utc, created_at_utc);

CREATE INDEX IF NOT EXISTS ix_input_batches_task
ON input_batches(task_id, first_message_sequence);

CREATE TABLE IF NOT EXISTS agent_results (
    result_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL CHECK(attempt_no >= 1),
    agent_id TEXT NOT NULL,
    agent_kind TEXT NOT NULL,
    invocation_id TEXT NOT NULL,
    result_kind TEXT NOT NULL,
    schema_version TEXT NOT NULL,
    context_version TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected', 'expired')),
    decision_code TEXT,
    created_at_utc TEXT NOT NULL,
    decided_at_utc TEXT,
    source TEXT NOT NULL DEFAULT 'agent_run',
    FOREIGN KEY(task_id) REFERENCES conversation_tasks(task_id),
    UNIQUE(task_id, attempt_no),
    CHECK(
        (status = 'pending' AND decision_code IS NULL AND decided_at_utc IS NULL)
        OR (status <> 'pending' AND decision_code IS NOT NULL AND decided_at_utc IS NOT NULL)
    )
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_results_approved_task
ON agent_results(task_id)
WHERE status = 'approved';

CREATE INDEX IF NOT EXISTS ix_agent_results_task_status
ON agent_results(task_id, status, attempt_no);

-- These columns are nullable because old M0 rows remain readable until the
-- new Runtime becomes the sole execution path.  New Runtime writes enforce
-- the corresponding links in RuntimeMessageRepository.
ALTER TABLE messages
ADD COLUMN input_batch_id TEXT REFERENCES input_batches(input_batch_id);

ALTER TABLE messages
ADD COLUMN result_id TEXT REFERENCES agent_results(result_id);

ALTER TABLE messages
ADD COLUMN bubble_index INTEGER CHECK(bubble_index IS NULL OR bubble_index >= 0);

-- The M0 uniqueness rule allowed only one character message per trigger.  The
-- new result/bubble relation is the authoritative duplicate-prevention rule.
DROP INDEX IF EXISTS uq_character_reply_to_message;

CREATE UNIQUE INDEX IF NOT EXISTS uq_messages_result_bubble
ON messages(result_id, bubble_index)
WHERE result_id IS NOT NULL;

CREATE INDEX IF NOT EXISTS ix_messages_input_batch
ON messages(input_batch_id, message_sequence);

CREATE INDEX IF NOT EXISTS ix_messages_result
ON messages(result_id, bubble_index);
