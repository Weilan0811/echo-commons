CREATE TABLE memory_activity_episodes (
    participation_id TEXT PRIMARY KEY NOT NULL, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    game_id TEXT NOT NULL, conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    membership_id TEXT NOT NULL REFERENCES conversation_memberships(membership_id),
    game_type TEXT NOT NULL, joined_at_utc TEXT NOT NULL, closed_at_utc TEXT,
    through_event_sequence INTEGER NOT NULL DEFAULT 0,
    materials_complete INTEGER NOT NULL DEFAULT 0 CHECK(materials_complete IN (0,1)),
    summary_digest_id TEXT REFERENCES memory_digests(digest_id),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id)
);
CREATE TABLE memory_activity_event_refs (
    community_id TEXT NOT NULL, character_id TEXT NOT NULL, event_id TEXT NOT NULL,
    participation_id TEXT NOT NULL REFERENCES memory_activity_episodes(participation_id),
    event_sequence INTEGER NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(character_id,event_id),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id)
);
ALTER TABLE memory_segments ADD COLUMN activity_participation_id TEXT
    REFERENCES memory_activity_episodes(participation_id);
ALTER TABLE memory_summary_batches ADD COLUMN activity_participation_id TEXT
    REFERENCES memory_activity_episodes(participation_id);
CREATE INDEX activity_segments ON memory_segments(activity_participation_id,position);

CREATE TABLE memory_segment_scenes_new (
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id),
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    first_sequence INTEGER NOT NULL CHECK(first_sequence>=0),
    last_sequence INTEGER NOT NULL CHECK(last_sequence>=first_sequence),
    boundary_json TEXT NOT NULL CHECK(json_valid(boundary_json)),
    PRIMARY KEY(segment_id,conversation_id)
);
INSERT INTO memory_segment_scenes_new SELECT * FROM memory_segment_scenes;
DROP TABLE memory_segment_scenes;
ALTER TABLE memory_segment_scenes_new RENAME TO memory_segment_scenes;
CREATE INDEX segment_scenes_conversation ON memory_segment_scenes(conversation_id,segment_id);


CREATE TABLE memory_segment_sources_new (
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought','game_event')), source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    ordinal INTEGER NOT NULL CHECK(ordinal >= 0),
    PRIMARY KEY(segment_id, source_kind, source_id), UNIQUE(segment_id, ordinal)
);

INSERT INTO memory_segment_sources_new SELECT * FROM memory_segment_sources;

DROP TABLE memory_segment_sources;

ALTER TABLE memory_segment_sources_new RENAME TO memory_segment_sources;

CREATE TABLE memory_segment_context_new (
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought','game_event')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL, ordinal INTEGER NOT NULL,
    PRIMARY KEY(segment_id,source_kind,source_id), UNIQUE(segment_id,ordinal)
);

INSERT INTO memory_segment_context_new SELECT * FROM memory_segment_context;

DROP TABLE memory_segment_context;

ALTER TABLE memory_segment_context_new RENAME TO memory_segment_context;

CREATE TABLE memory_source_coverage_new (
    community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    owner_kind TEXT NOT NULL CHECK(owner_kind IN ('segment_summary','diary')), owner_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought','game_event','segment_summary')), source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(character_id, owner_kind, owner_id, source_kind, source_id),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id)
);

INSERT INTO memory_source_coverage_new SELECT * FROM memory_source_coverage;

DROP TABLE memory_source_coverage;

ALTER TABLE memory_source_coverage_new RENAME TO memory_source_coverage;

CREATE INDEX coverage_source ON memory_source_coverage(character_id, source_kind, source_id);

CREATE TABLE memory_fact_sources_new (
    memory_id TEXT NOT NULL, version INTEGER NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','game_event','author_chunk')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(memory_id,version,source_kind,source_id,source_version),
    FOREIGN KEY(memory_id,version) REFERENCES memory_facts(memory_id,version)
);

INSERT INTO memory_fact_sources_new SELECT * FROM memory_fact_sources;

DROP TABLE memory_fact_sources;

ALTER TABLE memory_fact_sources_new RENAME TO memory_fact_sources;

CREATE TABLE memory_organization_coverage_new (
    community_id TEXT NOT NULL, character_id TEXT NOT NULL, batch_id TEXT NOT NULL,
    stage TEXT NOT NULL CHECK(stage IN ('facts','cognitions')),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought','game_event','author_chunk')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(character_id,stage,source_kind,source_id,source_version),
    FOREIGN KEY(character_id,batch_id,stage)
        REFERENCES memory_organization_stages(character_id,batch_id,stage)
);

INSERT INTO memory_organization_coverage_new SELECT * FROM memory_organization_coverage;

DROP TABLE memory_organization_coverage;

ALTER TABLE memory_organization_coverage_new RENAME TO memory_organization_coverage;

CREATE TABLE relation_evidence_sources_new (
    evidence_id TEXT NOT NULL REFERENCES relation_evidence(evidence_id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought','game_event','author_material')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(evidence_id,source_kind,source_id)
);

INSERT INTO relation_evidence_sources_new SELECT * FROM relation_evidence_sources;

DROP TABLE relation_evidence_sources;

ALTER TABLE relation_evidence_sources_new RENAME TO relation_evidence_sources;

CREATE TABLE character_state_sources_new (
    entry_id TEXT NOT NULL REFERENCES character_state_entries(entry_id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought','game_event')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(entry_id,source_kind,source_id)
);

INSERT INTO character_state_sources_new SELECT * FROM character_state_sources;

DROP TABLE character_state_sources;

ALTER TABLE character_state_sources_new RENAME TO character_state_sources;

CREATE TABLE memory_search_documents_new (
    document_id INTEGER PRIMARY KEY, community_id TEXT NOT NULL, character_id TEXT NOT NULL,
    conversation_id TEXT,
    source_kind TEXT NOT NULL CHECK(source_kind IN
        ('memory_fact','memory_cognition','message','author_chunk','segment_summary','conversation_digest')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL, occurred_at_utc TEXT,
    searchable INTEGER NOT NULL DEFAULT 1 CHECK(searchable IN (0,1)), updated_at_utc TEXT NOT NULL,
    UNIQUE(character_id,source_kind,source_id),
    FOREIGN KEY(community_id,character_id) REFERENCES character_instances(community_id,character_id),
    FOREIGN KEY(community_id,conversation_id) REFERENCES conversations(community_id,conversation_id)
);
INSERT INTO memory_search_documents_new SELECT * FROM memory_search_documents;
DROP TABLE memory_search_documents;
ALTER TABLE memory_search_documents_new RENAME TO memory_search_documents;
CREATE INDEX search_scope ON memory_search_documents(character_id,searchable,source_kind);
