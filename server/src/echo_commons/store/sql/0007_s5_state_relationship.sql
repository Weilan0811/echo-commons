-- S5 durable self-state entries and directed relationship facts.
-- Relationship snapshots are scoped to the owner account and are intentionally
-- separate from the global character availability row in character_states.
-- State history is append-only: the greatest version is current, and its expiry
-- does not revive an older value.

CREATE TABLE IF NOT EXISTS character_state_entries (
    entry_id TEXT PRIMARY KEY,
    character_id TEXT NOT NULL CHECK(length(trim(character_id)) > 0),
    state_kind TEXT NOT NULL CHECK(state_kind IN ('physical', 'mood', 'activity')),
    value TEXT NOT NULL CHECK(length(trim(value)) > 0),
    source_kind TEXT NOT NULL CHECK(length(trim(source_kind)) > 0),
    source_ref TEXT NOT NULL CHECK(length(trim(source_ref)) > 0),
    state_version INTEGER NOT NULL CHECK(state_version >= 1),
    recorded_at_utc TEXT NOT NULL,
    expires_at_utc TEXT,
    UNIQUE(character_id, state_kind, state_version),
    UNIQUE(character_id, state_kind, source_kind, source_ref),
    CHECK(expires_at_utc IS NULL OR expires_at_utc > recorded_at_utc)
);

CREATE INDEX IF NOT EXISTS ix_character_state_entry_latest
ON character_state_entries(character_id, state_kind, state_version DESC);

CREATE INDEX IF NOT EXISTS ix_character_state_entry_expiry
ON character_state_entries(expires_at_utc, character_id)
WHERE expires_at_utc IS NOT NULL;

CREATE TABLE IF NOT EXISTS relation_evidence (
    evidence_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    observer_character_id TEXT NOT NULL CHECK(length(trim(observer_character_id)) > 0),
    target_kind TEXT NOT NULL CHECK(target_kind IN ('account', 'character')),
    target_id TEXT NOT NULL CHECK(length(trim(target_id)) > 0),
    evidence_kind TEXT NOT NULL CHECK(length(trim(evidence_kind)) > 0),
    source_kind TEXT NOT NULL CHECK(length(trim(source_kind)) > 0),
    source_ref TEXT NOT NULL CHECK(length(trim(source_ref)) > 0),
    occurred_at_utc TEXT NOT NULL,
    recorded_at_utc TEXT NOT NULL,
    UNIQUE(
        account_id, observer_character_id, target_kind, target_id, source_kind, source_ref
    ),
    UNIQUE(evidence_id, account_id, observer_character_id, target_kind, target_id),
    CHECK(recorded_at_utc >= occurred_at_utc)
);

CREATE INDEX IF NOT EXISTS ix_relation_evidence_scope_time
ON relation_evidence(
    account_id, observer_character_id, target_kind, target_id, occurred_at_utc, evidence_id
);

CREATE TABLE IF NOT EXISTS relationship_state (
    account_id TEXT NOT NULL CHECK(length(trim(account_id)) > 0),
    observer_character_id TEXT NOT NULL CHECK(length(trim(observer_character_id)) > 0),
    target_kind TEXT NOT NULL CHECK(target_kind IN ('account', 'character')),
    target_id TEXT NOT NULL CHECK(length(trim(target_id)) > 0),
    relationship_type TEXT NOT NULL
        CHECK(relationship_type IN ('stranger', 'acquaintance', 'friend')),
    affection REAL CHECK(affection IS NULL OR affection BETWEEN 0.0 AND 100.0),
    trust REAL CHECK(trust IS NULL OR trust BETWEEN 0.0 AND 100.0),
    attachment REAL CHECK(attachment IS NULL OR attachment BETWEEN 0.0 AND 100.0),
    friend_qualifying_evidence_id TEXT,
    attitude_summary TEXT NOT NULL DEFAULT '',
    attitude_source_refs_json TEXT NOT NULL DEFAULT '[]'
        CHECK(
            json_valid(attitude_source_refs_json) = 1
            AND CASE
                WHEN json_valid(attitude_source_refs_json) = 1
                THEN json_type(attitude_source_refs_json) = 'array'
                ELSE 0
            END
        ),
    state_version INTEGER NOT NULL CHECK(state_version >= 0),
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(account_id, observer_character_id, target_kind, target_id),
    FOREIGN KEY(
        friend_qualifying_evidence_id,
        account_id,
        observer_character_id,
        target_kind,
        target_id
    ) REFERENCES relation_evidence(
        evidence_id, account_id, observer_character_id, target_kind, target_id
    ),
    CHECK(
        (relationship_type = 'stranger'
            AND affection IS NULL AND trust IS NULL AND attachment IS NULL)
        OR
        (relationship_type IN ('acquaintance', 'friend')
            AND affection IS NOT NULL AND trust IS NOT NULL AND attachment IS NOT NULL)
    ),
    CHECK(
        relationship_type <> 'stranger'
        OR (length(trim(attitude_summary)) = 0 AND attitude_source_refs_json = '[]')
    ),
    CHECK(
        (relationship_type = 'stranger' AND friend_qualifying_evidence_id IS NULL)
        OR relationship_type = 'acquaintance'
        OR (relationship_type = 'friend' AND friend_qualifying_evidence_id IS NOT NULL)
    ),
    CHECK(
        (length(trim(attitude_summary)) = 0 AND attitude_source_refs_json = '[]')
        OR (length(trim(attitude_summary)) > 0 AND attitude_source_refs_json <> '[]')
    )
);
