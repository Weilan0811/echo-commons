CREATE TABLE reflection_draft_steps (
    step_id INTEGER PRIMARY KEY AUTOINCREMENT,
    node_task_id TEXT NOT NULL REFERENCES reflection_node_tasks(node_task_id) ON DELETE CASCADE,
    execution_generation INTEGER NOT NULL,
    attempt INTEGER NOT NULL,
    revision INTEGER NOT NULL CHECK(revision >= 0),
    phase TEXT NOT NULL CHECK(phase IN ('writer', 'diagnosis')),
    draft_step_id INTEGER REFERENCES reflection_draft_steps(step_id),
    invocation_id TEXT NOT NULL,
    request_json TEXT NOT NULL,
    result_json TEXT,
    report_json TEXT,
    error_code TEXT,
    duration_ms INTEGER NOT NULL DEFAULT 0,
    created_at_utc TEXT NOT NULL,
    finished_at_utc TEXT
);
CREATE INDEX reflection_draft_steps_node
    ON reflection_draft_steps(node_task_id, execution_generation, step_id);
