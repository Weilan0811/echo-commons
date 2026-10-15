CREATE TABLE memory_segments_new (
    segment_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    position INTEGER NOT NULL CHECK(position > 0),
    started_at_utc TEXT NOT NULL, ended_at_utc TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('sealed','ingested')), source_version TEXT NOT NULL,
    summary_text TEXT, summary_version TEXT, sealed_at_utc TEXT NOT NULL, ingested_at_utc TEXT,
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    UNIQUE(character_id,position), UNIQUE(character_id,segment_id),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id),
    CHECK(ended_at_utc >= started_at_utc),
    CHECK((status='sealed' AND ingested_at_utc IS NULL) OR (status='ingested' AND ingested_at_utc IS NOT NULL)),
    CHECK((summary_text IS NULL AND summary_version IS NULL) OR (summary_text IS NOT NULL AND summary_version IS NOT NULL))
);
INSERT INTO memory_segments_new
SELECT m.segment_id,m.community_id,m.character_id,
    row_number() OVER (PARTITION BY m.character_id ORDER BY m.sealed_at_utc,m.segment_id),
    COALESCE((SELECT min(x.created_at_utc) FROM memory_segment_sources s JOIN messages x ON x.message_id=s.source_id WHERE s.segment_id=m.segment_id AND s.source_kind='message'),m.sealed_at_utc),
    COALESCE((SELECT max(x.created_at_utc) FROM memory_segment_sources s JOIN messages x ON x.message_id=s.source_id WHERE s.segment_id=m.segment_id AND s.source_kind='message'),m.sealed_at_utc),
    m.status,m.source_version,m.summary_text,m.summary_version,m.sealed_at_utc,m.ingested_at_utc,m.created_at_utc,m.updated_at_utc
FROM memory_segments m;

CREATE TABLE memory_segment_scenes (
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id),
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    first_sequence INTEGER NOT NULL CHECK(first_sequence>0),
    last_sequence INTEGER NOT NULL CHECK(last_sequence>=first_sequence),
    boundary_json TEXT NOT NULL CHECK(json_valid(boundary_json)),
    PRIMARY KEY(segment_id,conversation_id)
);
INSERT INTO memory_segment_scenes
SELECT m.segment_id,m.conversation_id,m.first_message_sequence,m.last_message_sequence,
    json_object('conversation_id',m.conversation_id,'kind',v.kind,
        'name',CASE v.kind WHEN 'direct' THEN '历史私聊' ELSE '历史群聊' END,
        'upper_sequence',m.last_message_sequence,
        'membership_ids',json((SELECT json_group_array(x.membership_id) FROM conversation_memberships x WHERE x.conversation_id=m.conversation_id AND x.actor_kind='character' AND x.actor_id=m.character_id AND x.joined_at_utc<=m.sealed_at_utc)))
FROM memory_segments m JOIN conversations v USING(conversation_id);

CREATE TABLE memory_segment_context (
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL, ordinal INTEGER NOT NULL,
    PRIMARY KEY(segment_id,source_kind,source_id), UNIQUE(segment_id,ordinal)
);

CREATE TABLE thoughts_new (
    thought_id TEXT PRIMARY KEY NOT NULL, result_id TEXT NOT NULL UNIQUE REFERENCES conversation_results(result_id),
    community_id TEXT NOT NULL, character_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    game_day TEXT NOT NULL CHECK(date(game_day) IS NOT NULL AND date(game_day)=game_day),
    content TEXT, content_version TEXT NOT NULL, segment_id TEXT,
    created_at_utc TEXT NOT NULL, content_removed_at_utc TEXT,
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id),
    FOREIGN KEY(community_id,conversation_id) REFERENCES conversations(community_id,conversation_id),
    FOREIGN KEY(character_id,segment_id) REFERENCES memory_segments(character_id,segment_id),
    CHECK((content IS NOT NULL AND length(trim(content))>0 AND content_removed_at_utc IS NULL) OR
          (content IS NULL AND content_removed_at_utc IS NOT NULL AND content_removed_at_utc>=created_at_utc))
);
INSERT INTO thoughts_new SELECT * FROM thoughts;

CREATE TABLE memory_summary_batch_digests (
    batch_id TEXT NOT NULL REFERENCES memory_summary_batches(batch_id),
    digest_id TEXT NOT NULL REFERENCES memory_digests(digest_id),
    ordinal INTEGER NOT NULL CHECK(ordinal>=0), PRIMARY KEY(batch_id,digest_id), UNIQUE(batch_id,ordinal)
);
INSERT INTO memory_summary_batch_digests SELECT batch_id,previous_digest_id,0 FROM memory_summary_batches WHERE previous_digest_id IS NOT NULL;

CREATE TABLE memory_digests (
    digest_id TEXT PRIMARY KEY NOT NULL, batch_id TEXT NOT NULL UNIQUE REFERENCES memory_summary_batches(batch_id),
    content TEXT NOT NULL CHECK(length(trim(content))>0), content_version TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
INSERT INTO memory_digests SELECT digest_id,batch_id,content,content_version,created_at_utc FROM conversation_digests;

CREATE TABLE memory_digest_segments (
    digest_id TEXT NOT NULL REFERENCES memory_digests(digest_id),
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id), summary_version TEXT NOT NULL,
    PRIMARY KEY(digest_id,segment_id)
);
INSERT INTO memory_digest_segments
SELECT d.digest_id,m.segment_id,COALESCE(m.summary_version,'') FROM conversation_digests d
JOIN memory_summary_batches b USING(batch_id)
JOIN memory_segments m ON m.character_id=b.character_id AND m.conversation_id=b.conversation_id
WHERE m.status='ingested' AND m.last_message_sequence<=d.covers_through_sequence;

CREATE TABLE memory_continuity_consumption (
    segment_id TEXT PRIMARY KEY NOT NULL REFERENCES memory_segments(segment_id),
    digest_id TEXT REFERENCES memory_digests(digest_id), consumed_at_utc TEXT NOT NULL
);
INSERT INTO memory_continuity_consumption
SELECT s.segment_id,s.digest_id,d.created_at_utc FROM memory_digest_segments s JOIN memory_digests d USING(digest_id)
WHERE s.digest_id=(SELECT latest.digest_id FROM memory_digest_segments other JOIN memory_digests latest USING(digest_id) WHERE other.segment_id=s.segment_id ORDER BY latest.created_at_utc DESC,latest.digest_id DESC LIMIT 1);

CREATE TABLE memory_summary_batches_new (
    batch_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    source_version TEXT NOT NULL, created_at_utc TEXT NOT NULL,
    organization_sources_json TEXT CHECK(organization_sources_json IS NULL OR json_valid(organization_sources_json)),
    UNIQUE(character_id,source_version),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id)
);
INSERT INTO memory_summary_batches_new SELECT batch_id,community_id,character_id,source_version,created_at_utc,organization_sources_json FROM memory_summary_batches;

DROP TABLE thoughts;
DROP TABLE memory_segments;
ALTER TABLE thoughts_new RENAME TO thoughts;
ALTER TABLE memory_segments_new RENAME TO memory_segments;
DROP TABLE conversation_digests;
DROP TABLE memory_summary_batches;
ALTER TABLE memory_summary_batches_new RENAME TO memory_summary_batches;
CREATE INDEX segments_order ON memory_segments(character_id,position);
CREATE INDEX segments_pending ON memory_segments(status,sealed_at_utc,segment_id);
CREATE INDEX thoughts_day ON thoughts(character_id,game_day,created_at_utc);
CREATE INDEX thoughts_segment ON thoughts(segment_id);
CREATE INDEX segment_scenes_conversation ON memory_segment_scenes(conversation_id,segment_id);

INSERT INTO memory_source_coverage
SELECT m.community_id,m.character_id,'segment_summary',m.segment_id,s.source_kind,s.source_id,s.source_version
FROM memory_segments m JOIN memory_segment_sources s USING(segment_id) WHERE m.status='ingested'
ON CONFLICT DO NOTHING;

CREATE TABLE relation_evidence_sources (
    evidence_id TEXT NOT NULL REFERENCES relation_evidence(evidence_id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(evidence_id,source_kind,source_id)
);
INSERT INTO relation_evidence_sources
SELECT e.evidence_id,s.source_kind,s.source_id,s.source_version FROM relation_evidence e
JOIN memory_segment_sources s ON e.source_kind='memory_segment' AND e.source_ref=s.segment_id;

INSERT INTO relation_evidence_sources
SELECT e.evidence_id,'message',m.message_id,'1' FROM relation_evidence e
JOIN messages m ON e.source_kind='message' AND e.source_ref=m.message_id;

CREATE TABLE conversation_tasks_new (
    task_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, conversation_id TEXT NOT NULL,
    social_turn_id TEXT NOT NULL, character_id TEXT NOT NULL, membership_id TEXT NOT NULL,
    snapshot_id TEXT NOT NULL UNIQUE,
    snapshot_schema_version INTEGER NOT NULL DEFAULT 2 CHECK(snapshot_schema_version=2),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','processing','retry_wait','suspended','completed','failed','cancelled')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count>=0),
    lease_generation INTEGER NOT NULL DEFAULT 0 CHECK(lease_generation>=0),
    available_at_utc TEXT NOT NULL, lease_owner TEXT, lease_until_utc TEXT, last_error_code TEXT,
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL, trace_id TEXT NOT NULL,
    UNIQUE(social_turn_id,character_id),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id),
    FOREIGN KEY(community_id,conversation_id,social_turn_id) REFERENCES social_turns(community_id,conversation_id,social_turn_id),
    FOREIGN KEY(social_turn_id,character_id) REFERENCES participation_decisions(social_turn_id,character_id),
    FOREIGN KEY(community_id,conversation_id,membership_id) REFERENCES conversation_memberships(community_id,conversation_id,membership_id),
    CHECK((status='processing' AND lease_owner IS NOT NULL AND lease_until_utc IS NOT NULL) OR
          (status!='processing' AND lease_owner IS NULL AND lease_until_utc IS NULL))
);
INSERT INTO conversation_tasks_new
SELECT task_id,community_id,conversation_id,social_turn_id,character_id,membership_id,snapshot_id,
    2,snapshot_json,status,attempt_count,lease_generation,available_at_utc,lease_owner,lease_until_utc,
    last_error_code,created_at_utc,updated_at_utc,trace_id FROM conversation_tasks;
DROP TABLE conversation_tasks;
ALTER TABLE conversation_tasks_new RENAME TO conversation_tasks;
CREATE INDEX tasks_claim ON conversation_tasks(status,available_at_utc,created_at_utc,task_id);

CREATE TABLE reflection_graph_runs_new (
    graph_run_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    graph_kind TEXT NOT NULL, graph_version TEXT NOT NULL, context_snapshot_id TEXT NOT NULL,
    snapshot_schema_version INTEGER NOT NULL DEFAULT 2 CHECK(snapshot_schema_version>=1),
    snapshot_json TEXT NOT NULL CHECK(json_valid(snapshot_json)), snapshot_fingerprint TEXT NOT NULL,
    source_scope_json TEXT NOT NULL CHECK(json_valid(source_scope_json)), source_scope_fingerprint TEXT NOT NULL,
    topology_node_keys_json TEXT NOT NULL CHECK(json_valid(topology_node_keys_json)),
    required_node_keys_json TEXT NOT NULL CHECK(json_valid(required_node_keys_json)),
    registered_node_keys_json TEXT NOT NULL CHECK(json_valid(registered_node_keys_json)),
    status TEXT NOT NULL CHECK(status IN ('pending','running','retry_wait','completed','partial','failed','cancelled')),
    execution_generation INTEGER NOT NULL DEFAULT 0 CHECK(execution_generation>=0),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL, started_at_utc TEXT, completed_at_utc TEXT,
    last_error_code TEXT, trace_id TEXT,
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id),
    UNIQUE(character_id,graph_kind,graph_version,context_snapshot_id,source_scope_fingerprint),
    CHECK((status IN ('completed','partial','failed','cancelled') AND completed_at_utc IS NOT NULL) OR
          (status IN ('pending','running','retry_wait') AND completed_at_utc IS NULL))
);
INSERT INTO reflection_graph_runs_new
SELECT graph_run_id,community_id,character_id,graph_kind,graph_version,context_snapshot_id,snapshot_schema_version,
    snapshot_json,snapshot_fingerprint,source_scope_json,source_scope_fingerprint,topology_node_keys_json,
    required_node_keys_json,registered_node_keys_json,status,execution_generation,created_at_utc,
    updated_at_utc,started_at_utc,completed_at_utc,last_error_code,trace_id FROM reflection_graph_runs;
DROP TABLE reflection_graph_runs;
ALTER TABLE reflection_graph_runs_new RENAME TO reflection_graph_runs;
CREATE INDEX graphs_recovery ON reflection_graph_runs(status,updated_at_utc,graph_run_id);

CREATE TABLE character_state_sources (
    entry_id TEXT NOT NULL REFERENCES character_state_entries(entry_id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(entry_id,source_kind,source_id)
);
INSERT INTO character_state_sources
SELECT e.entry_id,s.source_kind,s.source_id,s.source_version FROM character_state_entries e
JOIN memory_segment_sources s ON e.source_kind='memory_segment' AND e.source_ref=s.segment_id;
