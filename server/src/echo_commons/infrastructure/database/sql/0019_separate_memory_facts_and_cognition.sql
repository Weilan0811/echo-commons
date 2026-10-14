CREATE TABLE memory_facts (
    memory_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
    community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    topic TEXT NOT NULL CHECK(length(trim(topic))>0),
    content TEXT NOT NULL CHECK(length(trim(content))>0),
    participants_json TEXT NOT NULL CHECK(json_valid(participants_json)),
    conditions TEXT NOT NULL, occurred_at_utc TEXT, learned_at_utc TEXT NOT NULL,
    salience REAL NOT NULL CHECK(salience BETWEEN 0 AND 1),
    source_kind TEXT NOT NULL, source_ref TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('current','superseded','invalid')),
    PRIMARY KEY(memory_id,version),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id)
);
CREATE UNIQUE INDEX current_memory_fact ON memory_facts(memory_id) WHERE status='current';
CREATE INDEX memory_fact_scope ON memory_facts(character_id,status,salience DESC);

CREATE TABLE memory_cognitions (
    memory_id TEXT NOT NULL, version INTEGER NOT NULL CHECK(version>0),
    community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    topic TEXT NOT NULL CHECK(length(trim(topic))>0),
    content TEXT NOT NULL CHECK(length(trim(content))>0),
    formed_at_utc TEXT, applies_to TEXT NOT NULL CHECK(length(trim(applies_to))>0),
    target_json TEXT CHECK(target_json IS NULL OR json_valid(target_json)),
    salience REAL NOT NULL CHECK(salience BETWEEN 0 AND 1),
    source_kind TEXT NOT NULL, source_ref TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('current','superseded','invalid','needs_review')),
    PRIMARY KEY(memory_id,version),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id)
);
CREATE UNIQUE INDEX current_memory_cognition ON memory_cognitions(memory_id)
    WHERE status IN ('current','needs_review');
CREATE INDEX memory_cognition_scope ON memory_cognitions(character_id,status,salience DESC);

CREATE TABLE memory_fact_sources (
    memory_id TEXT NOT NULL, version INTEGER NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','author_chunk')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(memory_id,version,source_kind,source_id,source_version),
    FOREIGN KEY(memory_id,version) REFERENCES memory_facts(memory_id,version)
);
CREATE TABLE memory_cognition_sources (
    memory_id TEXT NOT NULL, version INTEGER NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('thought','author_chunk')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(memory_id,version,source_kind,source_id,source_version),
    FOREIGN KEY(memory_id,version) REFERENCES memory_cognitions(memory_id,version)
);
CREATE TABLE memory_cognition_fact_supports (
    memory_id TEXT NOT NULL, version INTEGER NOT NULL,
    fact_id TEXT NOT NULL, fact_version INTEGER NOT NULL,
    PRIMARY KEY(memory_id,version,fact_id,fact_version),
    FOREIGN KEY(memory_id,version) REFERENCES memory_cognitions(memory_id,version),
    FOREIGN KEY(fact_id,fact_version) REFERENCES memory_facts(memory_id,version)
);

-- 预置内容保留作者原文身份，与故事和采访一起成为整理来源。
CREATE TABLE memory_author_materials_new (
    material_id TEXT PRIMARY KEY NOT NULL,
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    blueprint_id TEXT NOT NULL, blueprint_version TEXT NOT NULL,
    material_kind TEXT NOT NULL CHECK(material_kind IN ('story','interview','preload')),
    position INTEGER NOT NULL CHECK(position>=0), content TEXT NOT NULL,
    question_id TEXT, question TEXT, created_at_utc TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'recallable' CHECK(visibility IN ('resident','recallable','private')),
    salience REAL NOT NULL DEFAULT 0.5 CHECK(salience BETWEEN 0 AND 1),
    UNIQUE(character_id,material_kind,position),
    CHECK((material_kind IN ('story','preload') AND question_id IS NULL AND question IS NULL)
       OR (material_kind='interview' AND question_id IS NOT NULL AND question IS NOT NULL))
);
INSERT INTO memory_author_materials_new
    (material_id,character_id,blueprint_id,blueprint_version,material_kind,position,content,
     question_id,question,created_at_utc) SELECT * FROM memory_author_materials;
INSERT INTO memory_author_materials_new
SELECT 'preload:'||e.memory_id,e.character_id,c.blueprint_id,e.content_version,'preload',
    ROW_NUMBER() OVER (PARTITION BY e.character_id ORDER BY e.memory_id)-1,
    e.content,NULL,NULL,e.recorded_at_utc,e.visibility,e.salience
FROM memory_entries e JOIN character_instances c USING(character_id)
WHERE e.source_kind='blueprint_preload';
DROP TABLE memory_author_materials;
ALTER TABLE memory_author_materials_new RENAME TO memory_author_materials;

CREATE TABLE memory_organization_stages (
    community_id TEXT NOT NULL, character_id TEXT NOT NULL, batch_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('facts','cognitions')),
    outcome TEXT NOT NULL CHECK(outcome IN ('completed','no_op')),
    references_json TEXT NOT NULL CHECK(json_valid(references_json)),
    completed_at_utc TEXT NOT NULL,
    PRIMARY KEY(character_id,batch_id,stage),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id)
);
CREATE TABLE memory_organization_coverage (
    community_id TEXT NOT NULL, character_id TEXT NOT NULL, batch_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('facts','cognitions')),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought','author_chunk')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(character_id,stage,source_kind,source_id,source_version),
    FOREIGN KEY(character_id,batch_id,stage)
        REFERENCES memory_organization_stages(character_id,batch_id,stage)
);
ALTER TABLE memory_summary_batches ADD COLUMN organization_sources_json TEXT
    CHECK(organization_sources_json IS NULL OR json_valid(organization_sources_json));
ALTER TABLE memory_views ADD COLUMN supporting_records_json TEXT NOT NULL DEFAULT '[]'
    CHECK(json_valid(supporting_records_json));

CREATE TABLE memory_search_documents_new (
    document_id INTEGER PRIMARY KEY, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    conversation_id TEXT,
    source_kind TEXT NOT NULL CHECK(source_kind IN
        ('memory_fact','memory_cognition','message','author_chunk','segment_summary')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL, occurred_at_utc TEXT,
    searchable INTEGER NOT NULL DEFAULT 1 CHECK(searchable IN (0,1)), updated_at_utc TEXT NOT NULL,
    UNIQUE(character_id,source_kind,source_id),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id),
    FOREIGN KEY(community_id,conversation_id) REFERENCES conversations(community_id,conversation_id)
);
DELETE FROM memory_vectors WHERE document_id IN
    (SELECT document_id FROM memory_search_documents WHERE source_kind='memory_entry');
DELETE FROM memory_vector_failures WHERE document_id IN
    (SELECT document_id FROM memory_search_documents WHERE source_kind='memory_entry');
DELETE FROM memory_search_fts WHERE rowid IN
    (SELECT document_id FROM memory_search_documents WHERE source_kind='memory_entry');
INSERT INTO memory_search_documents_new SELECT * FROM memory_search_documents
    WHERE source_kind!='memory_entry';
DROP TABLE memory_search_documents;
ALTER TABLE memory_search_documents_new RENAME TO memory_search_documents;
CREATE INDEX search_scope ON memory_search_documents(character_id,searchable,source_kind);

CREATE TABLE memory_changes_new (
    change_id INTEGER PRIMARY KEY, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    fact_kind TEXT NOT NULL CHECK(fact_kind IN
        ('memory_fact','memory_cognition','character_state','relationship')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL, created_at_utc TEXT NOT NULL, batch_id TEXT,
    UNIQUE(character_id,fact_kind,source_id,source_version),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id)
);
INSERT INTO memory_changes_new SELECT * FROM memory_changes WHERE fact_kind!='memory_entry';
DROP TABLE memory_changes;
ALTER TABLE memory_changes_new RENAME TO memory_changes;

-- 原文和审计保留；旧整理与视图协议的未完成执行停止。
UPDATE reflection_node_tasks SET status='skipped',lease_owner=NULL,lease_until_utc=NULL,
    lease_generation=lease_generation+1,last_error_code='reflection_contract_replaced',
    updated_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE status IN ('pending','processing','retry_wait') AND graph_run_id IN (
    SELECT graph_run_id FROM reflection_graph_runs WHERE graph_kind IN ('memory_organize','view_refresh')
);
UPDATE reflection_graph_runs SET status='cancelled',last_error_code='reflection_contract_replaced',
    execution_generation=execution_generation+1,
    updated_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),
    completed_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE graph_kind IN ('memory_organize','view_refresh')
    AND status IN ('pending','running','retry_wait','partial','failed');
DELETE FROM memory_organization_consumption;
UPDATE memory_change_batches SET outcome='superseded'
    WHERE outcome IS NULL;
UPDATE memory_changes SET batch_id=NULL;
DELETE FROM memory_views WHERE view_kind='core_memory';

INSERT INTO memory_initializations(character_id,phase,created_at_utc,updated_at_utc)
SELECT character_id,'materials',created_at_utc,strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
FROM character_instances WHERE memory_mode='full' AND character_id IN
    (SELECT character_id FROM memory_author_materials)
    AND character_id NOT IN (SELECT character_id FROM memory_initializations);
UPDATE memory_initializations SET phase='materials',organization_run_id=NULL,view_run_id=NULL,
    attempts=0,error_code=NULL,updated_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE character_id IN (SELECT character_id FROM character_instances WHERE memory_mode='full');
UPDATE character_instances SET memory_status='preparing'
WHERE memory_mode='full' AND character_id IN (SELECT character_id FROM memory_initializations);

DROP TABLE memory_entry_sources;
DROP TABLE memory_entries;
