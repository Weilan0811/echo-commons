-- Allow an optional Reflection node to fail while the available result is retained.

ALTER TABLE reflection_graph_runs RENAME TO reflection_graph_runs_0016_old;
ALTER TABLE reflection_node_tasks RENAME TO reflection_node_tasks_0016_old;
ALTER TABLE reflection_artifacts RENAME TO reflection_artifacts_0016_old;
ALTER TABLE reflection_graph_results RENAME TO reflection_graph_results_0016_old;

DROP INDEX ix_reflection_graph_runs_status;
DROP INDEX ix_reflection_node_tasks_claim;
DROP INDEX ix_reflection_node_tasks_graph_claim;
DROP INDEX ix_reflection_artifacts_graph;
DROP INDEX ix_reflection_artifacts_node;
DROP INDEX ix_reflection_graph_results_status;

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
        CHECK(status IN ('pending', 'running', 'retry_wait', 'completed', 'partial', 'failed', 'cancelled')),
    execution_generation INTEGER NOT NULL DEFAULT 0 CHECK(execution_generation >= 0),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    started_at_utc TEXT,
    completed_at_utc TEXT,
    last_error_code TEXT,
    trace_id TEXT,
    UNIQUE(
        account_id, character_id, graph_kind, graph_version,
        context_snapshot_id, source_scope_fingerprint
    ),
    CHECK(updated_at_utc >= created_at_utc),
    CHECK(started_at_utc IS NULL OR started_at_utc >= created_at_utc),
    CHECK(completed_at_utc IS NULL OR completed_at_utc >= created_at_utc),
    CHECK(
        (status IN ('completed', 'partial', 'failed', 'cancelled') AND completed_at_utc IS NOT NULL)
        OR (status NOT IN ('completed', 'partial', 'failed', 'cancelled') AND completed_at_utc IS NULL)
    ),
    CHECK(last_error_code IS NULL OR length(trim(last_error_code)) > 0),
    CHECK(trace_id IS NULL OR length(trim(trace_id)) > 0)
);

CREATE TABLE reflection_node_tasks (
    node_task_id TEXT PRIMARY KEY,
    graph_run_id TEXT NOT NULL REFERENCES reflection_graph_runs(graph_run_id),
    node_key TEXT NOT NULL CHECK(length(trim(node_key)) > 0),
    node_kind TEXT NOT NULL CHECK(length(trim(node_kind)) > 0),
    dependency_keys_json TEXT NOT NULL CHECK(json_valid(dependency_keys_json)),
    activated INTEGER NOT NULL CHECK(activated IN (0, 1)),
    node_input_fingerprint TEXT NOT NULL CHECK(length(trim(node_input_fingerprint)) > 0),
    input_artifact_refs_json TEXT NOT NULL CHECK(json_valid(input_artifact_refs_json)),
    output_contract_kind TEXT NOT NULL CHECK(length(trim(output_contract_kind)) > 0),
    output_contract_version TEXT NOT NULL CHECK(length(trim(output_contract_version)) > 0),
    status TEXT NOT NULL
        CHECK(status IN ('pending', 'processing', 'retry_wait', 'skipped', 'completed', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation >= 0),
    available_at_utc TEXT NOT NULL,
    lease_owner TEXT,
    lease_until_utc TEXT,
    artifact_id TEXT,
    last_error_code TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE(graph_run_id, node_key),
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

CREATE TABLE reflection_artifacts (
    artifact_id TEXT PRIMARY KEY,
    graph_run_id TEXT NOT NULL REFERENCES reflection_graph_runs(graph_run_id),
    node_task_id TEXT NOT NULL REFERENCES reflection_node_tasks(node_task_id),
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

CREATE TABLE reflection_graph_results (
    result_id TEXT PRIMARY KEY,
    graph_run_id TEXT NOT NULL UNIQUE REFERENCES reflection_graph_runs(graph_run_id),
    aggregate_fingerprint TEXT NOT NULL CHECK(length(trim(aggregate_fingerprint)) > 0),
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json)),
    status TEXT NOT NULL
        CHECK(status IN ('pending', 'approved', 'rejected', 'expired', 'skipped')),
    decision_code TEXT,
    created_at_utc TEXT NOT NULL,
    decided_at_utc TEXT,
    CHECK(decision_code IS NULL OR length(trim(decision_code)) > 0),
    CHECK(
        (status = 'pending' AND decision_code IS NULL AND decided_at_utc IS NULL)
        OR (status <> 'pending' AND decision_code IS NOT NULL AND decided_at_utc IS NOT NULL)
    ),
    CHECK(decided_at_utc IS NULL OR decided_at_utc >= created_at_utc)
);

INSERT INTO reflection_graph_runs
SELECT * FROM reflection_graph_runs_0016_old;

INSERT INTO reflection_node_tasks
SELECT * FROM reflection_node_tasks_0016_old;

INSERT INTO reflection_artifacts
SELECT * FROM reflection_artifacts_0016_old;

INSERT INTO reflection_graph_results
SELECT * FROM reflection_graph_results_0016_old;

DROP TABLE reflection_graph_results_0016_old;
DROP TABLE reflection_artifacts_0016_old;
DROP TABLE reflection_node_tasks_0016_old;
DROP TABLE reflection_graph_runs_0016_old;

CREATE INDEX ix_reflection_graph_runs_status
ON reflection_graph_runs(status, updated_at_utc, graph_run_id);

CREATE INDEX ix_reflection_node_tasks_claim
ON reflection_node_tasks(status, available_at_utc, created_at_utc, node_task_id);

CREATE INDEX ix_reflection_node_tasks_graph_claim
ON reflection_node_tasks(graph_run_id, status, activated, available_at_utc, node_task_id);

CREATE INDEX ix_reflection_artifacts_graph
ON reflection_artifacts(graph_run_id, created_at_utc, artifact_id);

CREATE INDEX ix_reflection_artifacts_node
ON reflection_artifacts(node_task_id, attempt);

CREATE INDEX ix_reflection_graph_results_status
ON reflection_graph_results(status, created_at_utc, result_id);
