CREATE TABLE memory_core_refreshes (
    batch_id TEXT PRIMARY KEY NOT NULL REFERENCES memory_change_batches(batch_id) ON DELETE CASCADE,
    request_kind TEXT NOT NULL CHECK(request_kind IN ('automatic','manual')),
    graph_run_id TEXT UNIQUE REFERENCES reflection_graph_runs(graph_run_id),
    outcome TEXT CHECK(outcome IN ('completed','no_op'))
);
