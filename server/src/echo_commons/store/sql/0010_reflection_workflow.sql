-- Reflection workflow results and small derived character views.
--
-- reflection_tasks remains the scheduler/lease identity.  One result row is
-- retained for each task attempt; authoritative memory, diary, state and
-- relationship rows are written separately in the same commit transaction.
CREATE TABLE IF NOT EXISTS reflection_results (
    result_id TEXT PRIMARY KEY,
    task_id TEXT NOT NULL,
    attempt_no INTEGER NOT NULL CHECK(attempt_no >= 1),
    agent_id TEXT NOT NULL CHECK(length(trim(agent_id)) > 0),
    agent_kind TEXT NOT NULL CHECK(length(trim(agent_kind)) > 0),
    invocation_id TEXT NOT NULL CHECK(length(trim(invocation_id)) > 0),
    branch TEXT NOT NULL CHECK(branch IN ('segment_ingest', 'phase_organize')),
    window_type TEXT,
    window_ref TEXT NOT NULL CHECK(length(trim(window_ref)) > 0),
    input_version TEXT NOT NULL CHECK(length(trim(input_version)) > 0),
    source_version TEXT NOT NULL CHECK(length(trim(source_version)) > 0),
    context_version TEXT NOT NULL CHECK(length(trim(context_version)) > 0),
    result_kind TEXT NOT NULL CHECK(length(trim(result_kind)) > 0),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    status TEXT NOT NULL
        CHECK(status IN ('pending', 'approved', 'rejected', 'expired', 'skipped')),
    decision_code TEXT,
    created_at_utc TEXT NOT NULL,
    decided_at_utc TEXT,
    FOREIGN KEY(task_id) REFERENCES reflection_tasks(task_id),
    CHECK(window_type IS NULL OR window_type IN ('game_day', 'narrative_phase')),
    CHECK(
        (branch = 'segment_ingest' AND window_type IS NULL)
        OR (branch = 'phase_organize' AND window_type IS NOT NULL)
    ),
    CHECK(length(trim(decision_code)) > 0 OR decision_code IS NULL),
    CHECK(
        (status = 'pending' AND decision_code IS NULL AND decided_at_utc IS NULL)
        OR (status <> 'pending' AND decision_code IS NOT NULL AND decided_at_utc IS NOT NULL)
    ),
    CHECK(decided_at_utc IS NULL OR decided_at_utc >= created_at_utc),
    UNIQUE(task_id, attempt_no)
);

CREATE INDEX IF NOT EXISTS ix_reflection_results_window
ON reflection_results(
    task_id, branch, window_type, window_ref, source_version, created_at_utc
);

-- Derived prompt views.  They are replaceable projections, never independent
-- story facts.  Relationship attitude continues to live on relationship_state.
CREATE TABLE IF NOT EXISTS memory_views (
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    view_kind TEXT NOT NULL CHECK(view_kind IN ('core_memory', 'state_summary')),
    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
    source_refs_json TEXT NOT NULL CHECK(json_valid(source_refs_json)),
    content_version TEXT NOT NULL CHECK(length(trim(content_version)) > 0),
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(account_id, character_id, view_kind)
);

CREATE INDEX IF NOT EXISTS ix_memory_views_scope
ON memory_views(account_id, character_id, view_kind, updated_at_utc);
