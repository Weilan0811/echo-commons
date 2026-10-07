-- 自定义人物创作材料与固定资源；不改写已有角色和经历。
CREATE TABLE character_authoring_drafts (
    draft_id TEXT PRIMARY KEY NOT NULL,
    owner_player_id TEXT NOT NULL REFERENCES players(player_id),
    status TEXT NOT NULL CHECK(status IN ('draft','confirmed')),
    revision INTEGER NOT NULL CHECK(revision > 0),
    content_json TEXT NOT NULL,
    workflow_json TEXT NOT NULL,
    accepted_candidate_revision INTEGER,
    create_request_json TEXT NOT NULL,
    confirmed_blueprint_id TEXT REFERENCES custom_character_blueprints(blueprint_id),
    accepted_candidate_id TEXT REFERENCES character_authoring_candidates(candidate_id),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    CHECK((status = 'draft' AND confirmed_blueprint_id IS NULL)
       OR (status = 'confirmed' AND confirmed_blueprint_id IS NOT NULL))
);
CREATE INDEX character_drafts_owner ON character_authoring_drafts
    (owner_player_id, created_at_utc, draft_id);
CREATE TABLE character_authoring_candidates (
    candidate_id TEXT PRIMARY KEY NOT NULL,
    draft_id TEXT NOT NULL REFERENCES character_authoring_drafts(draft_id),
    input_revision INTEGER NOT NULL CHECK(input_revision > 0),
    operation TEXT NOT NULL CHECK(operation IN ('basic','story','interview','calibrate')),
    request_json TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('processing','completed','failed')),
    output_json TEXT,
    error_code TEXT,
    model_profile TEXT NOT NULL,
    model_requests INTEGER NOT NULL DEFAULT 0,
    usage_json TEXT NOT NULL DEFAULT '{}',
    deadline_utc TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    finished_at_utc TEXT,
    CHECK((status = 'processing' AND finished_at_utc IS NULL)
       OR (status != 'processing' AND finished_at_utc IS NOT NULL)),
    CHECK(status != 'completed' OR output_json IS NOT NULL)
);
CREATE INDEX character_candidates_draft ON character_authoring_candidates(draft_id);
CREATE TABLE custom_character_blueprints (
    blueprint_id TEXT PRIMARY KEY NOT NULL,
    source_draft_id TEXT NOT NULL UNIQUE REFERENCES character_authoring_drafts(draft_id),
    owner_player_id TEXT NOT NULL REFERENCES players(player_id),
    content_version TEXT NOT NULL,
    resource_json TEXT NOT NULL,
    materials_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE INDEX custom_blueprints_owner ON custom_character_blueprints
    (owner_player_id, created_at_utc, blueprint_id);
