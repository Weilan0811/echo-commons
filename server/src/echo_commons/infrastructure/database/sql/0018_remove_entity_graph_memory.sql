DROP TABLE memory_organization_entities;
DROP TABLE memory_entry_entities;
DROP TABLE memory_entity_aliases;
DROP TABLE memory_edges;
DROP TABLE memory_entities;
ALTER TABLE memory_entries DROP COLUMN subject_kind;
ALTER TABLE memory_entries DROP COLUMN subject_id;

CREATE TABLE memory_entry_sources (
    character_id TEXT NOT NULL,
    memory_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('segment_summary','author_chunk')),
    source_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    PRIMARY KEY(character_id,memory_id,source_kind,source_id,source_version),
    FOREIGN KEY(character_id,memory_id) REFERENCES memory_entries(character_id,memory_id)
);

-- 已替换的整理协议停止执行，原始材料和历史审计保留。
UPDATE reflection_node_tasks SET status='skipped',lease_owner=NULL,lease_until_utc=NULL,
    lease_generation=lease_generation+1,last_error_code='reflection_contract_replaced',
    updated_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE status IN ('pending','processing','retry_wait') AND graph_run_id IN (
    SELECT graph_run_id FROM reflection_graph_runs WHERE graph_kind='memory_organize'
);
UPDATE reflection_graph_runs SET status='cancelled',last_error_code='reflection_contract_replaced',
    execution_generation=execution_generation+1,
    updated_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),
    completed_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE graph_kind='memory_organize' AND status IN ('pending','running','retry_wait','partial','failed');
UPDATE character_instances SET memory_status='preparing',
    updated_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE character_id IN (
    SELECT character_id FROM memory_initializations WHERE phase='organize'
    AND organization_run_id IN (
        SELECT graph_run_id FROM reflection_graph_runs
        WHERE graph_kind='memory_organize' AND last_error_code='reflection_contract_replaced'
    )
);
UPDATE memory_initializations SET organization_run_id=NULL,attempts=0,error_code=NULL,
    updated_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE phase='organize' AND organization_run_id IN (
    SELECT graph_run_id FROM reflection_graph_runs WHERE graph_kind='memory_organize'
    AND last_error_code='reflection_contract_replaced'
);
