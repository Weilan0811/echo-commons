CREATE TABLE image_assets (
    asset_id TEXT PRIMARY KEY,
    owner_player_id TEXT REFERENCES players(player_id) ON DELETE SET NULL,
    purpose TEXT NOT NULL CHECK(purpose IN ('character_illustration','character_avatar','community_cover','chat_background')),
    source TEXT NOT NULL CHECK(source IN ('upload','generated','derived')),
    source_asset_id TEXT REFERENCES image_assets(asset_id),
    crop_json TEXT CHECK(crop_json IS NULL OR json_valid(crop_json)),
    request_id TEXT,
    request_json TEXT,
    status TEXT NOT NULL DEFAULT 'available' CHECK(status IN ('available','deleting')),
    created_at_utc TEXT NOT NULL,
    UNIQUE(owner_player_id,request_id),
    CHECK(status='deleting' OR owner_player_id IS NOT NULL)
);
CREATE TABLE image_asset_files (
    asset_id TEXT NOT NULL REFERENCES image_assets(asset_id) ON DELETE CASCADE,
    variant TEXT NOT NULL,
    relative_path TEXT NOT NULL,
    width INTEGER NOT NULL CHECK(width>0),
    height INTEGER NOT NULL CHECK(height>0),
    byte_size INTEGER NOT NULL CHECK(byte_size>0),
    PRIMARY KEY(asset_id,variant)
);
CREATE TABLE image_asset_references (
    owner_kind TEXT NOT NULL CHECK(owner_kind IN ('draft','blueprint','character','community')),
    owner_id TEXT NOT NULL,
    asset_id TEXT NOT NULL REFERENCES image_assets(asset_id),
    PRIMARY KEY(owner_kind,owner_id)
);
CREATE INDEX image_assets_owner ON image_assets(owner_player_id,created_at_utc,asset_id);
CREATE INDEX image_asset_references_asset ON image_asset_references(asset_id);
CREATE TABLE image_generations (
    generation_id TEXT PRIMARY KEY,
    owner_player_id TEXT NOT NULL REFERENCES players(player_id),
    client_request_id TEXT NOT NULL,
    purpose TEXT NOT NULL,
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    prompt TEXT NOT NULL,
    parameters_json TEXT NOT NULL CHECK(json_valid(parameters_json)),
    provider_task_id TEXT,
    status TEXT NOT NULL CHECK(status IN ('queued','submitting','generating','saving','completed','failed')),
    asset_id TEXT REFERENCES image_assets(asset_id),
    error_code TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    deadline_utc TEXT NOT NULL,
    UNIQUE(owner_player_id,client_request_id)
);
ALTER TABLE communities ADD COLUMN cover_kind TEXT CHECK(cover_kind IN ('preset','asset'));
ALTER TABLE communities ADD COLUMN cover_ref TEXT;
ALTER TABLE character_instances ADD COLUMN avatar_asset_id TEXT REFERENCES image_assets(asset_id);
ALTER TABLE character_instances ADD COLUMN appearance_version INTEGER NOT NULL DEFAULT 0;
