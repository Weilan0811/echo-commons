CREATE TABLE activity_inputs (
    input_id TEXT PRIMARY KEY,
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    game_id TEXT NOT NULL REFERENCES community_games(game_id),
    participation_id TEXT NOT NULL REFERENCES game_participations(participation_id),
    kind TEXT NOT NULL CHECK(kind IN ('turn','reply','reaction')),
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    preparation_json TEXT NOT NULL CHECK(json_valid(preparation_json)),
    memory_json TEXT CHECK(memory_json IS NULL OR json_valid(memory_json)),
    projection_json TEXT CHECK(projection_json IS NULL OR json_valid(projection_json)),
    analysis_json TEXT CHECK(analysis_json IS NULL OR json_valid(analysis_json)),
    snapshot_json TEXT CHECK(snapshot_json IS NULL OR json_valid(snapshot_json)),
    understanding_json TEXT CHECK(understanding_json IS NULL OR json_valid(understanding_json)),
    understood_at_utc TEXT,
    created_at_utc TEXT NOT NULL,
    CHECK((understanding_json IS NULL) = (understood_at_utc IS NULL)),
    FOREIGN KEY(community_id, character_id) REFERENCES character_instances(community_id, character_id)
);
CREATE INDEX activity_inputs_scope ON activity_inputs(community_id, character_id, game_id, participation_id);

CREATE TABLE activity_working_memory (
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    game_id TEXT NOT NULL REFERENCES community_games(game_id),
    participation_id TEXT NOT NULL REFERENCES game_participations(participation_id),
    version INTEGER NOT NULL CHECK(version >= 1),
    content_json TEXT NOT NULL CHECK(json_valid(content_json)),
    last_input_id TEXT NOT NULL REFERENCES activity_inputs(input_id),
    PRIMARY KEY(community_id, character_id, game_id, participation_id)
);

CREATE TABLE activity_observation_progress (
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    game_id TEXT NOT NULL REFERENCES community_games(game_id),
    participation_id TEXT NOT NULL REFERENCES game_participations(participation_id),
    event_sequence INTEGER NOT NULL DEFAULT 0 CHECK(event_sequence >= 0),
    message_sequence INTEGER NOT NULL DEFAULT 0 CHECK(message_sequence >= 0),
    version INTEGER NOT NULL DEFAULT 0 CHECK(version >= 0),
    PRIMARY KEY(community_id, character_id, game_id, participation_id)
);

CREATE TABLE activity_persona_projections (
    blueprint_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    projection_json TEXT NOT NULL CHECK(json_valid(projection_json)),
    request_json TEXT NOT NULL CHECK(json_valid(request_json)),
    response_json TEXT NOT NULL CHECK(json_valid(response_json)),
    PRIMARY KEY(blueprint_id, source_version)
);
