-- Durable Reflection task identity and lease state.
--
-- Reflection results, source watermarks and branch-specific material tables are
-- added by later migrations.  This table is intentionally limited to the
-- scheduling boundary so a Worker can be introduced without changing the
-- ConversationTask schema or the AgentResult foreign-key contract.
CREATE TABLE IF NOT EXISTS reflection_tasks (
    task_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    target_agent_id TEXT NOT NULL CHECK(length(trim(target_agent_id)) > 0),
    target_agent_kind TEXT NOT NULL CHECK(length(trim(target_agent_kind)) > 0),
    branch TEXT NOT NULL CHECK(branch IN ('segment_ingest', 'phase_organize')),
    window_type TEXT,
    window_ref TEXT NOT NULL CHECK(length(trim(window_ref)) > 0),
    input_version TEXT NOT NULL CHECK(length(trim(input_version)) > 0),
    source_version TEXT NOT NULL CHECK(length(trim(source_version)) > 0),
    idempotency_key TEXT NOT NULL CHECK(length(trim(idempotency_key)) > 0) UNIQUE,
    status TEXT NOT NULL
        CHECK(status IN ('pending', 'processing', 'retry_wait', 'deferred', 'completed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0),
    available_at_utc TEXT NOT NULL,
    lease_owner TEXT,
    lease_until_utc TEXT,
    last_error_code TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    trace_id TEXT NOT NULL CHECK(length(trim(trace_id)) > 0),
    CHECK(window_type IS NULL OR window_type IN ('game_day', 'narrative_phase')),
    CHECK(
        (branch = 'segment_ingest' AND window_type IS NULL)
        OR (branch = 'phase_organize' AND window_type IS NOT NULL)
    ),
    CHECK(updated_at_utc >= created_at_utc),
    CHECK(available_at_utc >= created_at_utc),
    CHECK(
        (status = 'processing'
            AND lease_owner IS NOT NULL
            AND length(trim(lease_owner)) > 0
            AND lease_until_utc IS NOT NULL
            AND lease_until_utc > updated_at_utc)
        OR (status <> 'processing' AND lease_owner IS NULL AND lease_until_utc IS NULL)
    ),
    CHECK(last_error_code IS NULL OR length(trim(last_error_code)) > 0)
);

-- A source window can be active once for each target Agent.  Terminal tasks
-- remain queryable and may be superseded by a later task when its input
-- version changes.
CREATE UNIQUE INDEX IF NOT EXISTS uq_reflection_active_window
ON reflection_tasks(
    account_id,
    character_id,
    target_agent_id,
    branch,
    IFNULL(window_type, ''),
    window_ref
)
WHERE status IN ('pending', 'processing', 'retry_wait', 'deferred');

CREATE INDEX IF NOT EXISTS ix_reflection_tasks_claim
ON reflection_tasks(status, available_at_utc, created_at_utc, task_id);

CREATE INDEX IF NOT EXISTS ix_reflection_tasks_scope
ON reflection_tasks(
    account_id,
    character_id,
    target_agent_id,
    branch,
    window_type,
    window_ref
);
