-- S6 source/page memory storage and rebuildable graph index boundaries.
--
-- messages remain the immutable conversation source.  memory_entries are the
-- independently recallable long-term memory pages; graph rows only index those
-- pages and never become an independent source of facts.

CREATE TABLE IF NOT EXISTS memory_segments (
    segment_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    conversation_id TEXT NOT NULL CHECK(length(trim(conversation_id)) > 0),
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    first_message_sequence INTEGER NOT NULL CHECK(first_message_sequence > 0),
    last_message_sequence INTEGER NOT NULL
        CHECK(last_message_sequence >= first_message_sequence),
    status TEXT NOT NULL CHECK(status IN ('sealed', 'ingested')),
    summary_text TEXT,
    source_version TEXT NOT NULL CHECK(length(trim(source_version)) > 0),
    sealed_at_utc TEXT NOT NULL,
    ingested_at_utc TEXT,
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    UNIQUE(
        account_id, conversation_id, character_id,
        first_message_sequence, last_message_sequence
    ),
    FOREIGN KEY(account_id, conversation_id)
        REFERENCES conversations(account_id, conversation_id),
    FOREIGN KEY(character_id) REFERENCES character_states(character_id),
    CHECK(updated_at_utc >= created_at_utc),
    CHECK(
        (status = 'sealed' AND ingested_at_utc IS NULL)
        OR (status = 'ingested' AND ingested_at_utc IS NOT NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_memory_segments_scope
ON memory_segments(account_id, character_id, conversation_id, first_message_sequence);

CREATE INDEX IF NOT EXISTS ix_memory_segments_status
ON memory_segments(status, sealed_at_utc, segment_id);

CREATE TABLE IF NOT EXISTS memory_entries (
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    memory_id TEXT NOT NULL CHECK(length(trim(memory_id)) > 0),
    memory_kind TEXT NOT NULL
        CHECK(memory_kind IN ('fact', 'event', 'preference', 'promise', 'thread', 'other')),
    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
    confidence REAL NOT NULL DEFAULT 1.0 CHECK(confidence BETWEEN 0.0 AND 1.0),
    salience REAL NOT NULL DEFAULT 0.5 CHECK(salience BETWEEN 0.0 AND 1.0),
    source_kind TEXT NOT NULL CHECK(length(trim(source_kind)) > 0),
    source_ref TEXT NOT NULL CHECK(length(trim(source_ref)) > 0),
    subject_kind TEXT NOT NULL CHECK(length(trim(subject_kind)) > 0),
    subject_id TEXT NOT NULL CHECK(length(trim(subject_id)) > 0),
    visibility TEXT NOT NULL CHECK(visibility IN ('resident', 'recallable', 'private')),
    content_version TEXT NOT NULL CHECK(length(trim(content_version)) > 0),
    occurred_at_utc TEXT,
    recorded_at_utc TEXT NOT NULL,
    expires_at_utc TEXT,
    invalidated_at_utc TEXT,
    PRIMARY KEY(account_id, character_id, memory_id),
    CHECK(expires_at_utc IS NULL OR expires_at_utc > recorded_at_utc),
    CHECK(invalidated_at_utc IS NULL OR invalidated_at_utc >= recorded_at_utc)
);

CREATE INDEX IF NOT EXISTS ix_memory_entries_resident
ON memory_entries(account_id, character_id, visibility, salience DESC, recorded_at_utc DESC)
WHERE invalidated_at_utc IS NULL;

CREATE INDEX IF NOT EXISTS ix_memory_entries_source
ON memory_entries(account_id, character_id, source_kind, source_ref);

CREATE TABLE IF NOT EXISTS diary_entries (
    diary_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    game_day TEXT NOT NULL CHECK(date(game_day) IS NOT NULL),
    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
    source_window_kind TEXT NOT NULL CHECK(length(trim(source_window_kind)) > 0),
    source_window_ref TEXT NOT NULL CHECK(length(trim(source_window_ref)) > 0),
    content_version TEXT NOT NULL CHECK(length(trim(content_version)) > 0),
    created_at_utc TEXT NOT NULL,
    UNIQUE(account_id, character_id, game_day)
);

CREATE INDEX IF NOT EXISTS ix_diary_entries_scope_day
ON diary_entries(account_id, character_id, game_day);

CREATE TABLE IF NOT EXISTS thoughts (
    thought_id TEXT PRIMARY KEY,
    result_id TEXT NOT NULL UNIQUE,
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    game_day TEXT NOT NULL CHECK(date(game_day) IS NOT NULL),
    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
    created_at_utc TEXT NOT NULL,
    FOREIGN KEY(result_id) REFERENCES agent_results(result_id)
);

CREATE INDEX IF NOT EXISTS ix_thoughts_scope_day
ON thoughts(account_id, character_id, game_day, created_at_utc, thought_id);

-- Rebuildable graph index.  These rows carry no independent story truth.
CREATE TABLE IF NOT EXISTS memory_entities (
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    entity_id TEXT NOT NULL CHECK(length(trim(entity_id)) > 0),
    entity_kind TEXT NOT NULL CHECK(length(trim(entity_kind)) > 0),
    canonical_name TEXT NOT NULL CHECK(length(trim(canonical_name)) > 0),
    created_at_utc TEXT NOT NULL,
    updated_at_utc TEXT NOT NULL,
    invalidated_at_utc TEXT,
    PRIMARY KEY(account_id, character_id, entity_id),
    CHECK(updated_at_utc >= created_at_utc),
    CHECK(invalidated_at_utc IS NULL OR invalidated_at_utc >= created_at_utc)
);

CREATE TABLE IF NOT EXISTS memory_entity_aliases (
    alias_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    entity_id TEXT NOT NULL CHECK(length(trim(entity_id)) > 0),
    alias_text TEXT NOT NULL CHECK(length(trim(alias_text)) > 0),
    normalized_alias TEXT NOT NULL CHECK(length(trim(normalized_alias)) > 0),
    created_at_utc TEXT NOT NULL,
    invalidated_at_utc TEXT,
    FOREIGN KEY(account_id, character_id, entity_id)
        REFERENCES memory_entities(account_id, character_id, entity_id),
    CHECK(invalidated_at_utc IS NULL OR invalidated_at_utc >= created_at_utc)
);

CREATE UNIQUE INDEX IF NOT EXISTS uq_memory_entity_aliases_active
ON memory_entity_aliases(account_id, character_id, normalized_alias)
WHERE invalidated_at_utc IS NULL;

CREATE INDEX IF NOT EXISTS ix_memory_entity_aliases_lookup
ON memory_entity_aliases(account_id, character_id, normalized_alias)
WHERE invalidated_at_utc IS NULL;

CREATE TABLE IF NOT EXISTS memory_entry_entities (
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    memory_id TEXT NOT NULL CHECK(length(trim(memory_id)) > 0),
    entity_id TEXT NOT NULL CHECK(length(trim(entity_id)) > 0),
    role TEXT NOT NULL CHECK(length(trim(role)) > 0),
    created_at_utc TEXT NOT NULL,
    PRIMARY KEY(account_id, character_id, memory_id, entity_id, role),
    FOREIGN KEY(account_id, character_id, memory_id)
        REFERENCES memory_entries(account_id, character_id, memory_id),
    FOREIGN KEY(account_id, character_id, entity_id)
        REFERENCES memory_entities(account_id, character_id, entity_id)
);

CREATE INDEX IF NOT EXISTS ix_memory_entry_entities_entity
ON memory_entry_entities(account_id, character_id, entity_id, memory_id);

CREATE TABLE IF NOT EXISTS memory_edges (
    edge_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    from_entity_id TEXT NOT NULL CHECK(length(trim(from_entity_id)) > 0),
    to_entity_id TEXT NOT NULL CHECK(length(trim(to_entity_id)) > 0),
    edge_kind TEXT NOT NULL CHECK(length(trim(edge_kind)) > 0),
    confidence REAL NOT NULL DEFAULT 1.0 CHECK(confidence BETWEEN 0.0 AND 1.0),
    source_memory_id TEXT,
    created_at_utc TEXT NOT NULL,
    invalidated_at_utc TEXT,
    FOREIGN KEY(account_id, character_id, from_entity_id)
        REFERENCES memory_entities(account_id, character_id, entity_id),
    FOREIGN KEY(account_id, character_id, to_entity_id)
        REFERENCES memory_entities(account_id, character_id, entity_id),
    FOREIGN KEY(account_id, character_id, source_memory_id)
        REFERENCES memory_entries(account_id, character_id, memory_id),
    UNIQUE(account_id, character_id, from_entity_id, to_entity_id, edge_kind, source_memory_id),
    CHECK(invalidated_at_utc IS NULL OR invalidated_at_utc >= created_at_utc)
);

CREATE INDEX IF NOT EXISTS ix_memory_edges_from
ON memory_edges(account_id, character_id, from_entity_id, edge_kind)
WHERE invalidated_at_utc IS NULL;

CREATE INDEX IF NOT EXISTS ix_memory_edges_to
ON memory_edges(account_id, character_id, to_entity_id, edge_kind)
WHERE invalidated_at_utc IS NULL;
