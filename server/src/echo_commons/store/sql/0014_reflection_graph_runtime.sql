-- Persist the frozen Reflection graph runtime boundary.
--
-- 0009-0013 are historical migrations and remain unchanged.  The legacy
-- reflection task/result rows are copied into new tables so graph NodeTasks
-- can use their canonical fields without manufacturing branch/window values.

CREATE TABLE reflection_graph_runs (
    graph_run_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    graph_kind TEXT NOT NULL CHECK(length(trim(graph_kind)) > 0),
    graph_version TEXT NOT NULL CHECK(length(trim(graph_version)) > 0),
    context_snapshot_id TEXT NOT NULL CHECK(length(trim(context_snapshot_id)) > 0),
    snapshot_fingerprint TEXT NOT NULL CHECK(length(trim(snapshot_fingerprint)) > 0),
    source_scope_json TEXT NOT NULL CHECK(json_valid(source_scope_json)),
    source_scope_fingerprint TEXT NOT NULL CHECK(length(trim(source_scope_fingerprint)) > 0),
    topology_node_keys_json TEXT NOT NULL CHECK(json_valid(topology_node_keys_json)),
    required_node_keys_json TEXT NOT NULL CHECK(json_valid(required_node_keys_json)),
    registered_node_keys_json TEXT NOT NULL CHECK(json_valid(registered_node_keys_json)),
    status TEXT NOT NULL
        CHECK(status IN ('pending', 'running', 'retry_wait', 'deferred', 'completed', 'failed', 'cancelled')),
    fence_generation INTEGER NOT NULL DEFAULT 0 CHECK(fence_generation >= 0),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    started_at_utc TEXT,
    completed_at_utc TEXT,
    last_error_code TEXT,
    trace_id TEXT,
    UNIQUE(
        account_id,
        character_id,
        graph_kind,
        graph_version,
        context_snapshot_id,
        source_scope_fingerprint
    ),
    CHECK(updated_at_utc >= created_at_utc),
    CHECK(started_at_utc IS NULL OR started_at_utc >= created_at_utc),
    CHECK(completed_at_utc IS NULL OR completed_at_utc >= created_at_utc),
    CHECK(
        (status IN ('completed', 'failed', 'cancelled') AND completed_at_utc IS NOT NULL)
        OR (status NOT IN ('completed', 'failed', 'cancelled') AND completed_at_utc IS NULL)
    ),
    CHECK(last_error_code IS NULL OR length(trim(last_error_code)) > 0),
    CHECK(trace_id IS NULL OR length(trim(trace_id)) > 0)
);

CREATE INDEX ix_reflection_graph_runs_status
ON reflection_graph_runs(status, updated_at_utc, graph_run_id);

ALTER TABLE reflection_results RENAME TO reflection_results_0014_legacy;
ALTER TABLE reflection_tasks RENAME TO reflection_tasks_0014_legacy;

DROP INDEX IF EXISTS uq_reflection_runnable_window;
DROP INDEX IF EXISTS ix_reflection_tasks_claim;
DROP INDEX IF EXISTS ix_reflection_tasks_scope;
DROP INDEX IF EXISTS ix_reflection_results_window;

CREATE TABLE reflection_tasks (
    -- Legacy task identity and lifecycle columns.  They stay nullable for
    -- graph rows and are read only by the compatibility ReflectionTask path.
    task_id TEXT PRIMARY KEY,
    account_id TEXT,
    character_id TEXT,
    target_agent_id TEXT,
    target_agent_kind TEXT,
    branch TEXT,
    window_type TEXT,
    window_ref TEXT,
    input_version TEXT,
    source_version TEXT,
    idempotency_key TEXT NOT NULL CHECK(length(trim(idempotency_key)) > 0) UNIQUE,
    status TEXT NOT NULL
        CHECK(status IN ('pending', 'processing', 'retry_wait', 'deferred', 'skipped', 'completed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0),
    available_at_utc TEXT NOT NULL,
    lease_owner TEXT,
    lease_until_utc TEXT,
    last_error_code TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    trace_id TEXT,

    -- Canonical graph NodeTask identity and scheduling state.
    graph_run_id TEXT REFERENCES reflection_graph_runs(graph_run_id),
    node_key TEXT,
    node_kind TEXT,
    dependency_keys_json TEXT NOT NULL DEFAULT '[]' CHECK(json_valid(dependency_keys_json)),
    activated INTEGER NOT NULL DEFAULT 1 CHECK(activated IN (0, 1)),
    node_input_fingerprint TEXT,
    input_artifact_refs_json TEXT NOT NULL DEFAULT '[]'
        CHECK(json_valid(input_artifact_refs_json)),
    output_contract_kind TEXT,
    output_contract_version TEXT,
    artifact_id TEXT,

    CHECK(
        (graph_run_id IS NULL
            AND node_key IS NULL
            AND node_kind IS NULL
            AND node_input_fingerprint IS NULL
            AND output_contract_kind IS NULL
            AND output_contract_version IS NULL
            AND artifact_id IS NULL)
        OR (graph_run_id IS NOT NULL
            AND length(trim(node_key)) > 0
            AND length(trim(node_kind)) > 0
            AND length(trim(node_input_fingerprint)) > 0
            AND length(trim(output_contract_kind)) > 0
            AND length(trim(output_contract_version)) > 0)
    ),
    CHECK(
        (status = 'processing'
            AND lease_owner IS NOT NULL
            AND length(trim(lease_owner)) > 0
            AND lease_until_utc IS NOT NULL
            AND lease_until_utc > updated_at_utc)
        OR (status <> 'processing' AND lease_owner IS NULL AND lease_until_utc IS NULL)
    ),
    CHECK(last_error_code IS NULL OR length(trim(last_error_code)) > 0),
    CHECK(updated_at_utc >= created_at_utc),
    CHECK(available_at_utc >= created_at_utc),
    CHECK(graph_run_id IS NOT NULL OR (
        account_id IS NOT NULL
        AND character_id IS NOT NULL
        AND target_agent_id IS NOT NULL
        AND target_agent_kind IS NOT NULL
        AND branch IN ('segment_ingest', 'phase_organize')
        AND window_ref IS NOT NULL
        AND input_version IS NOT NULL
        AND source_version IS NOT NULL
        AND trace_id IS NOT NULL
    )),
    CHECK(graph_run_id IS NOT NULL OR (
        (branch = 'segment_ingest' AND window_type IS NULL)
        OR (branch = 'phase_organize' AND window_type IN ('game_day', 'narrative_phase'))
    )),
    CHECK(graph_run_id IS NOT NULL OR length(trim(account_id)) > 0),
    CHECK(graph_run_id IS NOT NULL OR length(trim(character_id)) > 0),
    CHECK(graph_run_id IS NOT NULL OR length(trim(target_agent_id)) > 0),
    CHECK(graph_run_id IS NOT NULL OR length(trim(target_agent_kind)) > 0),
    CHECK(graph_run_id IS NOT NULL OR length(trim(window_ref)) > 0),
    CHECK(graph_run_id IS NOT NULL OR length(trim(input_version)) > 0),
    CHECK(graph_run_id IS NOT NULL OR length(trim(source_version)) > 0),
    CHECK(graph_run_id IS NOT NULL OR length(trim(trace_id)) > 0)
);

INSERT INTO reflection_tasks(
    task_id, account_id, character_id, target_agent_id, target_agent_kind,
    branch, window_type, window_ref, input_version, source_version,
    idempotency_key, status, attempt_count, lease_generation,
    available_at_utc, lease_owner, lease_until_utc, last_error_code,
    created_at_utc, updated_at_utc, trace_id
)
SELECT
    task_id, account_id, character_id, target_agent_id, target_agent_kind,
    branch, window_type, window_ref, input_version, source_version,
    idempotency_key, status, attempt_count, lease_generation,
    available_at_utc, lease_owner, lease_until_utc, last_error_code,
    created_at_utc, updated_at_utc, trace_id
FROM reflection_tasks_0014_legacy;

CREATE UNIQUE INDEX uq_reflection_runnable_window
ON reflection_tasks(
    account_id,
    character_id,
    target_agent_id,
    branch,
    IFNULL(window_type, ''),
    window_ref
)
WHERE graph_run_id IS NULL AND status IN ('pending', 'processing', 'retry_wait');

CREATE UNIQUE INDEX uq_reflection_graph_node
ON reflection_tasks(graph_run_id, node_key)
WHERE graph_run_id IS NOT NULL;

CREATE INDEX ix_reflection_tasks_claim
ON reflection_tasks(status, available_at_utc, created_at_utc, task_id);

CREATE INDEX ix_reflection_tasks_scope
ON reflection_tasks(
    account_id,
    character_id,
    target_agent_id,
    branch,
    window_type,
    window_ref
);

CREATE INDEX ix_reflection_tasks_graph_claim
ON reflection_tasks(graph_run_id, status, activated, available_at_utc, created_at_utc, task_id)
WHERE graph_run_id IS NOT NULL;

CREATE TABLE reflection_artifacts (
    artifact_id TEXT PRIMARY KEY,
    graph_run_id TEXT NOT NULL REFERENCES reflection_graph_runs(graph_run_id),
    node_task_id TEXT NOT NULL REFERENCES reflection_tasks(task_id),
    invocation_id TEXT,
    attempt INTEGER NOT NULL CHECK(attempt >= 1),
    node_input_fingerprint TEXT NOT NULL CHECK(length(trim(node_input_fingerprint)) > 0),
    output_contract_kind TEXT NOT NULL CHECK(length(trim(output_contract_kind)) > 0),
    output_contract_version TEXT NOT NULL CHECK(length(trim(output_contract_version)) > 0),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    content_fingerprint TEXT NOT NULL CHECK(length(trim(content_fingerprint)) > 0),
    evidence_refs_json TEXT NOT NULL CHECK(json_valid(evidence_refs_json)),
    audit_json TEXT NOT NULL DEFAULT '{}' CHECK(json_valid(audit_json)),
    created_at_utc TEXT NOT NULL,
    UNIQUE(node_task_id, attempt),
    CHECK(invocation_id IS NULL OR length(trim(invocation_id)) > 0)
);

CREATE INDEX ix_reflection_artifacts_graph
ON reflection_artifacts(graph_run_id, created_at_utc, artifact_id);

CREATE INDEX ix_reflection_artifacts_node
ON reflection_artifacts(node_task_id, attempt);

CREATE TABLE reflection_results (
    result_id TEXT PRIMARY KEY,
    task_id TEXT,
    attempt_no INTEGER CHECK(attempt_no IS NULL OR attempt_no >= 1),
    agent_id TEXT,
    agent_kind TEXT,
    invocation_id TEXT,
    branch TEXT,
    window_type TEXT,
    window_ref TEXT,
    input_version TEXT,
    source_version TEXT,
    context_version TEXT,
    result_kind TEXT,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    status TEXT NOT NULL
        CHECK(status IN ('pending', 'approved', 'rejected', 'expired', 'skipped')),
    decision_code TEXT,
    created_at_utc TEXT NOT NULL,
    decided_at_utc TEXT,
    result_scope TEXT NOT NULL DEFAULT 'legacy_batch'
        CHECK(result_scope IN ('legacy_batch', 'node_artifact', 'graph_batch')),
    graph_run_id TEXT REFERENCES reflection_graph_runs(graph_run_id),
    node_task_id TEXT REFERENCES reflection_tasks(task_id),
    artifact_id TEXT REFERENCES reflection_artifacts(artifact_id),
    CHECK(length(trim(decision_code)) > 0 OR decision_code IS NULL),
    CHECK(
        (status = 'pending' AND decision_code IS NULL AND decided_at_utc IS NULL)
        OR (status <> 'pending' AND decision_code IS NOT NULL AND decided_at_utc IS NOT NULL)
    ),
    CHECK(decided_at_utc IS NULL OR decided_at_utc >= created_at_utc),
    CHECK(
        (result_scope = 'legacy_batch'
            AND task_id IS NOT NULL
            AND attempt_no IS NOT NULL
            AND length(trim(agent_id)) > 0
            AND length(trim(agent_kind)) > 0
            AND length(trim(invocation_id)) > 0
            AND branch IN ('segment_ingest', 'phase_organize')
            AND window_ref IS NOT NULL
            AND length(trim(window_ref)) > 0
            AND length(trim(input_version)) > 0
            AND length(trim(source_version)) > 0
            AND length(trim(context_version)) > 0
            AND length(trim(result_kind)) > 0
            AND graph_run_id IS NULL
            AND node_task_id IS NULL
            AND artifact_id IS NULL
            AND (
                (branch = 'segment_ingest' AND window_type IS NULL)
                OR (branch = 'phase_organize' AND window_type IN ('game_day', 'narrative_phase'))
            ))
        OR (result_scope = 'node_artifact'
            AND task_id IS NULL
            AND graph_run_id IS NOT NULL
            AND node_task_id IS NOT NULL
            AND artifact_id IS NOT NULL)
        OR (result_scope = 'graph_batch'
            AND task_id IS NULL
            AND graph_run_id IS NOT NULL
            AND node_task_id IS NULL
            AND artifact_id IS NULL)
    ),
    FOREIGN KEY(task_id) REFERENCES reflection_tasks(task_id),
    UNIQUE(task_id, attempt_no)
);

INSERT INTO reflection_results(
    result_id, task_id, attempt_no, agent_id, agent_kind, invocation_id,
    branch, window_type, window_ref, input_version, source_version,
    context_version, result_kind, payload_json, status, decision_code,
    created_at_utc, decided_at_utc
)
SELECT
    result_id, task_id, attempt_no, agent_id, agent_kind, invocation_id,
    branch, window_type, window_ref, input_version, source_version,
    context_version, result_kind, payload_json, status, decision_code,
    created_at_utc, decided_at_utc
FROM reflection_results_0014_legacy;

CREATE INDEX ix_reflection_results_window
ON reflection_results(
    task_id, branch, window_type, window_ref, source_version, created_at_utc
);

CREATE INDEX ix_reflection_results_graph
ON reflection_results(graph_run_id, result_scope, created_at_utc, result_id);

DROP TABLE reflection_results_0014_legacy;
DROP TABLE reflection_tasks_0014_legacy;
