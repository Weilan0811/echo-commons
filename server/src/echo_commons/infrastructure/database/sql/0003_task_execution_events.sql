CREATE TABLE task_execution_events (
    event_id INTEGER PRIMARY KEY AUTOINCREMENT,
    event_kind TEXT NOT NULL,
    task_kind TEXT NOT NULL,
    task_id TEXT NOT NULL,
    attempt INTEGER NOT NULL CHECK(attempt >= 0),
    lease_generation INTEGER NOT NULL CHECK(lease_generation >= 0),
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    graph_run_id TEXT,
    graph_execution_generation INTEGER,
    invocation_id TEXT,
    trace_id TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    payload_json TEXT NOT NULL CHECK(json_valid(payload_json))
);
CREATE INDEX idx_execution_events_task ON task_execution_events(task_kind,task_id,event_id);
CREATE INDEX idx_execution_events_graph ON task_execution_events(graph_run_id,event_id);
