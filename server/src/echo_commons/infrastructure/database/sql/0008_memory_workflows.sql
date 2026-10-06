CREATE TABLE memory_author_batches (
    batch_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    chunk_ids_json TEXT NOT NULL CHECK(json_valid(chunk_ids_json)),
    outcome TEXT CHECK(outcome IN ('completed','no_op')),
    created_at_utc TEXT NOT NULL,
    consumed_at_utc TEXT,
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id)
);
CREATE TABLE memory_changes (
    change_id INTEGER PRIMARY KEY,
    community_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    fact_kind TEXT NOT NULL CHECK(fact_kind IN ('memory_entry','character_state','relationship')),
    source_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    batch_id TEXT,
    UNIQUE(character_id,fact_kind,source_id,source_version),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id)
);
CREATE TABLE memory_change_batches (
    batch_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    materials_json TEXT NOT NULL CHECK(json_valid(materials_json)),
    outcome TEXT CHECK(outcome IN ('completed','no_op','superseded')),
    created_at_utc TEXT NOT NULL,
    consumed_at_utc TEXT,
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id)
);
CREATE TABLE reflection_supplements (
    graph_run_id TEXT PRIMARY KEY REFERENCES reflection_graph_runs(graph_run_id),
    original_run_id TEXT NOT NULL REFERENCES reflection_graph_runs(graph_run_id),
    node_keys_json TEXT NOT NULL CHECK(json_valid(node_keys_json)),
    created_at_utc TEXT NOT NULL
);
CREATE TABLE memory_organization_entities (
    character_id TEXT NOT NULL,
    batch_id TEXT NOT NULL,
    local_id TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('memory_summary_batch','author_material_batch')),
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY(character_id,batch_id,local_id),
    FOREIGN KEY(character_id,entity_id) REFERENCES memory_entities(character_id,entity_id)
);
