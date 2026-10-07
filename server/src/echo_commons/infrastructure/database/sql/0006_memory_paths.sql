-- 已有实例保留完整记忆能力，新实例由创建入口明确填写模式。
ALTER TABLE character_instances ADD COLUMN memory_mode TEXT NOT NULL DEFAULT 'full'
    CHECK(memory_mode IN ('simple','full'));
ALTER TABLE character_instances ADD COLUMN memory_status TEXT NOT NULL DEFAULT 'ready'
    CHECK(memory_status IN ('preparing','ready','failed'));

-- 保留文档编号和全文索引，只扩展允许的正式来源。
CREATE TABLE memory_search_documents_new (
    document_id INTEGER PRIMARY KEY, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    conversation_id TEXT,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('memory_entry','message','author_chunk','segment_summary')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL, occurred_at_utc TEXT,
    searchable INTEGER NOT NULL DEFAULT 1 CHECK(searchable IN (0,1)), updated_at_utc TEXT NOT NULL,
    UNIQUE(character_id, source_kind, source_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id),
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id)
);
INSERT INTO memory_search_documents_new SELECT * FROM memory_search_documents;
DROP TABLE memory_search_documents;
ALTER TABLE memory_search_documents_new RENAME TO memory_search_documents;
CREATE INDEX search_scope ON memory_search_documents(character_id, searchable, source_kind);

CREATE TABLE memory_author_materials (
    material_id TEXT PRIMARY KEY NOT NULL,
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    blueprint_id TEXT NOT NULL,
    blueprint_version TEXT NOT NULL,
    material_kind TEXT NOT NULL CHECK(material_kind IN ('story','interview')),
    position INTEGER NOT NULL CHECK(position >= 0),
    content TEXT NOT NULL,
    question_id TEXT,
    question TEXT,
    created_at_utc TEXT NOT NULL,
    UNIQUE(character_id, material_kind, position),
    CHECK((material_kind='story' AND question_id IS NULL AND question IS NULL)
       OR (material_kind='interview' AND question_id IS NOT NULL AND question IS NOT NULL))
);
CREATE TABLE memory_author_chunks (
    chunk_id TEXT PRIMARY KEY NOT NULL,
    material_id TEXT NOT NULL REFERENCES memory_author_materials(material_id),
    position INTEGER NOT NULL CHECK(position >= 0),
    start_offset INTEGER NOT NULL CHECK(start_offset >= 0),
    end_offset INTEGER NOT NULL CHECK(end_offset > start_offset),
    content TEXT NOT NULL,
    UNIQUE(material_id, position)
);
CREATE TABLE memory_initializations (
    character_id TEXT PRIMARY KEY NOT NULL REFERENCES character_instances(character_id),
    phase TEXT NOT NULL CHECK(phase IN ('materials','organize','views','completed')),
    error_code TEXT,
    organization_run_id TEXT REFERENCES reflection_graph_runs(graph_run_id),
    view_run_id TEXT REFERENCES reflection_graph_runs(graph_run_id),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL
);
CREATE TABLE memory_vectors (
    document_id INTEGER PRIMARY KEY NOT NULL REFERENCES memory_search_documents(document_id)
        ON DELETE CASCADE,
    source_version TEXT NOT NULL,
    model_identity TEXT NOT NULL,
    dimensions INTEGER NOT NULL CHECK(dimensions > 0),
    vector BLOB NOT NULL,
    updated_at_utc TEXT NOT NULL
);

-- 固定创作资源保留原文，可为旧实例恢复材料；缺少材料的实例仍可使用。
INSERT INTO memory_author_materials
SELECT c.character_id || ':story', c.character_id, c.blueprint_id, c.blueprint_version,
       'story', 0, json_extract(b.materials_json, '$.story'), NULL, NULL, c.created_at_utc
FROM character_instances c JOIN custom_character_blueprints b ON c.blueprint_id=b.blueprint_id
WHERE c.blueprint_version=b.content_version
  AND length(trim(COALESCE(json_extract(b.materials_json, '$.story'), ''))) > 0;
INSERT INTO memory_author_materials
SELECT c.character_id || ':interview:' || q.key, c.character_id, c.blueprint_id,
       c.blueprint_version, 'interview', CAST(q.key AS INTEGER),
       json_extract(q.value, '$.answer'), json_extract(q.value, '$.question_id'),
       json_extract(q.value, '$.question'), c.created_at_utc
FROM character_instances c JOIN custom_character_blueprints b ON c.blueprint_id=b.blueprint_id,
     json_each(b.materials_json, '$.interview') q
WHERE c.blueprint_version=b.content_version
  AND length(trim(COALESCE(json_extract(q.value, '$.answer'), ''))) > 0;
