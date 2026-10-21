CREATE TABLE character_people (
    person_id TEXT PRIMARY KEY NOT NULL,
    owner_player_id TEXT NOT NULL REFERENCES players(player_id),
    display_name TEXT NOT NULL,
    description TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE INDEX character_people_owner ON character_people(owner_player_id,display_name,person_id);
CREATE TABLE character_person_bindings (
    community_id TEXT NOT NULL,
    person_id TEXT NOT NULL REFERENCES character_people(person_id),
    actor_kind TEXT NOT NULL CHECK(actor_kind IN ('player','character')),
    actor_id TEXT NOT NULL,
    PRIMARY KEY(community_id,person_id),
    UNIQUE(community_id,actor_kind,actor_id),
    FOREIGN KEY(community_id,actor_kind,actor_id)
        REFERENCES community_members(community_id,actor_kind,actor_id)
);
CREATE TABLE memory_initializations_new (
    character_id TEXT PRIMARY KEY NOT NULL REFERENCES character_instances(character_id),
    phase TEXT NOT NULL CHECK(phase IN ('relationships','materials','organize','views','completed')),
    error_code TEXT,
    organization_run_id TEXT REFERENCES reflection_graph_runs(graph_run_id),
    view_run_id TEXT REFERENCES reflection_graph_runs(graph_run_id),
    attempts INTEGER NOT NULL DEFAULT 0 CHECK(attempts >= 0),
    created_at_utc TEXT NOT NULL, updated_at_utc TEXT NOT NULL,
    relationship_input_json TEXT NOT NULL DEFAULT '{}',
    relationship_output_json TEXT
);
INSERT INTO memory_initializations_new
    (character_id,phase,error_code,organization_run_id,view_run_id,attempts,created_at_utc,updated_at_utc)
    SELECT * FROM memory_initializations;
DROP TABLE memory_initializations;
ALTER TABLE memory_initializations_new RENAME TO memory_initializations;

CREATE TABLE memory_author_materials_new (
    material_id TEXT PRIMARY KEY NOT NULL,
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    blueprint_id TEXT NOT NULL, blueprint_version TEXT NOT NULL,
    material_kind TEXT NOT NULL CHECK(material_kind IN ('story','interview','preload','relationship')),
    position INTEGER NOT NULL CHECK(position>=0), content TEXT NOT NULL,
    question_id TEXT, question TEXT, created_at_utc TEXT NOT NULL,
    visibility TEXT NOT NULL DEFAULT 'recallable' CHECK(visibility IN ('resident','recallable','private')),
    salience REAL NOT NULL DEFAULT 0.5 CHECK(salience BETWEEN 0 AND 1),
    UNIQUE(character_id,material_kind,position),
    CHECK((material_kind IN ('story','preload','relationship') AND question_id IS NULL AND question IS NULL)
       OR (material_kind='interview' AND question_id IS NOT NULL AND question IS NOT NULL))
);
INSERT INTO memory_author_materials_new SELECT * FROM memory_author_materials;
DROP TABLE memory_author_materials;
ALTER TABLE memory_author_materials_new RENAME TO memory_author_materials;

CREATE TABLE relation_evidence_sources_new (
    evidence_id TEXT NOT NULL REFERENCES relation_evidence(evidence_id),
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message','thought','author_material')),
    source_id TEXT NOT NULL, source_version TEXT NOT NULL,
    PRIMARY KEY(evidence_id,source_kind,source_id)
);
INSERT INTO relation_evidence_sources_new SELECT * FROM relation_evidence_sources;
DROP TABLE relation_evidence_sources;
ALTER TABLE relation_evidence_sources_new RENAME TO relation_evidence_sources;
