-- New development baseline. Legacy temporary thoughts are deliberately discarded.
DROP TABLE thoughts;
CREATE TABLE thoughts (
    thought_id TEXT PRIMARY KEY,
    result_id TEXT NOT NULL UNIQUE REFERENCES agent_results(result_id),
    account_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    game_day TEXT NOT NULL,
    content TEXT NOT NULL CHECK(length(trim(content)) > 0),
    content_version TEXT NOT NULL CHECK(length(content_version) > 0),
    created_at_utc TEXT NOT NULL,
    segment_id TEXT REFERENCES memory_segments(segment_id),
    FOREIGN KEY(account_id, conversation_id) REFERENCES conversations(account_id, conversation_id)
);
CREATE INDEX ix_thoughts_scope_day ON thoughts(account_id, character_id, game_day);
CREATE TRIGGER thought_result_scope BEFORE INSERT ON thoughts BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM agent_results r JOIN conversation_tasks t ON t.task_id=r.task_id
        WHERE r.result_id=NEW.result_id AND r.status='approved'
          AND t.account_id=NEW.account_id AND t.character_id=NEW.character_id
          AND t.conversation_id=NEW.conversation_id
          AND EXISTS(SELECT 1 FROM messages m WHERE m.result_id=r.result_id)
    ) THEN RAISE(ABORT, 'thought_result_scope_mismatch') END;
END;
CREATE TRIGGER thought_segment_scope BEFORE UPDATE OF segment_id ON thoughts
WHEN NEW.segment_id IS NOT NULL BEGIN
    SELECT CASE WHEN NOT EXISTS (
        SELECT 1 FROM memory_segments s WHERE s.segment_id=NEW.segment_id
          AND s.account_id=NEW.account_id AND s.character_id=NEW.character_id
          AND s.conversation_id=NEW.conversation_id
          AND NOT EXISTS(SELECT 1 FROM messages m WHERE m.result_id=NEW.result_id
              AND m.message_sequence NOT BETWEEN s.first_message_sequence AND s.last_message_sequence)
    ) THEN RAISE(ABORT, 'thought_segment_scope_mismatch') END;
END;
-- Retain identities and associations after private thought content is removed.
CREATE TABLE thought_provenance (
    thought_id TEXT PRIMARY KEY,
    result_id TEXT NOT NULL UNIQUE REFERENCES agent_results(result_id),
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    game_day TEXT NOT NULL,
    content_version TEXT NOT NULL,
    segment_id TEXT REFERENCES memory_segments(segment_id)
);
CREATE TRIGGER thought_provenance_insert AFTER INSERT ON thoughts BEGIN
    INSERT INTO thought_provenance VALUES (NEW.thought_id,NEW.result_id,NEW.account_id,
        NEW.conversation_id,NEW.character_id,NEW.game_day,NEW.content_version,NEW.segment_id);
END;
CREATE TRIGGER thought_provenance_bind AFTER UPDATE OF segment_id ON thoughts BEGIN
    UPDATE thought_provenance SET segment_id=NEW.segment_id WHERE thought_id=NEW.thought_id;
END;
CREATE INDEX thoughts_segment ON thoughts(segment_id);
ALTER TABLE memory_segments ADD COLUMN summary_version TEXT;

CREATE TABLE memory_source_coverage (
    owner_kind TEXT NOT NULL CHECK(owner_kind IN ('segment_summary', 'diary')),
    owner_id TEXT NOT NULL,
    source_kind TEXT NOT NULL CHECK(source_kind IN ('message', 'thought', 'segment_summary')),
    source_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    PRIMARY KEY(owner_kind, owner_id, source_kind, source_id)
);
CREATE INDEX memory_coverage_source ON memory_source_coverage(source_kind, source_id);

CREATE TABLE memory_summary_batches (
    batch_id TEXT PRIMARY KEY,
    account_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    character_id TEXT NOT NULL,
    source_version TEXT NOT NULL,
    previous_digest_id TEXT,
    created_at_utc TEXT NOT NULL,
    UNIQUE(account_id, conversation_id, character_id, source_version),
    FOREIGN KEY(account_id, conversation_id) REFERENCES conversations(account_id, conversation_id)
);
CREATE TABLE memory_summary_batch_items (
    batch_id TEXT NOT NULL REFERENCES memory_summary_batches(batch_id),
    ordinal INTEGER NOT NULL,
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id),
    summary_version TEXT NOT NULL,
    PRIMARY KEY(batch_id, ordinal),
    UNIQUE(batch_id, segment_id)
);
CREATE TABLE conversation_digests (
    digest_id TEXT PRIMARY KEY,
    batch_id TEXT NOT NULL UNIQUE REFERENCES memory_summary_batches(batch_id),
    previous_digest_id TEXT REFERENCES conversation_digests(digest_id),
    content TEXT NOT NULL,
    content_version TEXT NOT NULL,
    covers_through_sequence INTEGER NOT NULL,
    created_at_utc TEXT NOT NULL
);
CREATE TABLE memory_organization_consumption (
    segment_id TEXT NOT NULL REFERENCES memory_segments(segment_id),
    summary_version TEXT NOT NULL,
    batch_id TEXT NOT NULL REFERENCES memory_summary_batches(batch_id),
    outcome TEXT NOT NULL CHECK(outcome IN ('completed','no_op')),
    consumed_at_utc TEXT NOT NULL,
    PRIMARY KEY(segment_id, summary_version)
);

ALTER TABLE memory_views ADD COLUMN source_snapshot_version TEXT;
