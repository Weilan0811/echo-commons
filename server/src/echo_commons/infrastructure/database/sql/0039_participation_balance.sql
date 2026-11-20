CREATE TABLE social_participation_shares (
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    statistics_key TEXT NOT NULL,
    character_id TEXT NOT NULL,
    expected_share REAL NOT NULL DEFAULT 0 CHECK(expected_share BETWEEN 0 AND 1),
    actual_share REAL NOT NULL DEFAULT 0 CHECK(actual_share BETWEEN 0 AND 1),
    PRIMARY KEY(conversation_id,statistics_key,character_id)
);
CREATE TABLE social_participation_publications (
    message_id TEXT PRIMARY KEY REFERENCES messages(message_id),
    statistics_key TEXT NOT NULL
);
