CREATE TABLE memory_relationship_refreshes (
    batch_id TEXT PRIMARY KEY REFERENCES memory_change_batches(batch_id),
    community_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    target_kind TEXT NOT NULL CHECK(target_kind IN ('player','character')),
    target_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    request_kind TEXT NOT NULL CHECK(request_kind IN ('automatic','missing','manual')),
    request_id TEXT,
    request_target_json TEXT,
    graph_run_id TEXT REFERENCES reflection_graph_runs(graph_run_id),
    error_code TEXT,
    created_at_utc TEXT NOT NULL
);
CREATE INDEX relationship_refresh_target ON memory_relationship_refreshes
    (community_id,character_id,target_kind,target_id,source_version);
CREATE INDEX relationship_refresh_request ON memory_relationship_refreshes(request_id);
