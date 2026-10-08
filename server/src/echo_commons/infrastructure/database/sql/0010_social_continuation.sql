CREATE TABLE social_chains (
    chain_id TEXT PRIMARY KEY NOT NULL,
    community_id TEXT NOT NULL,
    conversation_id TEXT NOT NULL,
    root_turn_id TEXT NOT NULL UNIQUE,
    max_messages INTEGER NOT NULL CHECK(max_messages > 0),
    max_tasks INTEGER NOT NULL CHECK(max_tasks > 0),
    message_count INTEGER NOT NULL DEFAULT 0 CHECK(message_count >= 0 AND message_count <= max_messages),
    task_count INTEGER NOT NULL DEFAULT 0 CHECK(task_count >= 0 AND task_count <= max_tasks),
    status TEXT NOT NULL CHECK(status IN ('active','completed','cancelled')),
    stop_reason TEXT,
    created_at_utc TEXT NOT NULL,
    completed_at_utc TEXT,
    FOREIGN KEY(community_id, conversation_id) REFERENCES conversations(community_id, conversation_id),
    FOREIGN KEY(root_turn_id) REFERENCES social_turns(social_turn_id) DEFERRABLE INITIALLY DEFERRED,
    UNIQUE(community_id, conversation_id, chain_id),
    CHECK((status = 'active' AND stop_reason IS NULL AND completed_at_utc IS NULL)
       OR (status <> 'active' AND stop_reason IS NOT NULL AND completed_at_utc IS NOT NULL))
);
CREATE UNIQUE INDEX chains_active ON social_chains(conversation_id) WHERE status = 'active';

ALTER TABLE social_turns ADD COLUMN chain_id TEXT REFERENCES social_chains(chain_id);
ALTER TABLE social_turns ADD COLUMN parent_turn_id TEXT REFERENCES social_turns(social_turn_id);
ALTER TABLE social_turns ADD COLUMN depth INTEGER NOT NULL DEFAULT 0 CHECK(depth >= 0);
ALTER TABLE social_turns ADD COLUMN policy_version TEXT;
ALTER TABLE social_turns ADD COLUMN stop_reason TEXT;

CREATE TABLE social_candidates (
    social_turn_id TEXT NOT NULL REFERENCES social_turns(social_turn_id),
    character_id TEXT NOT NULL,
    membership_id TEXT NOT NULL REFERENCES conversation_memberships(membership_id),
    status TEXT NOT NULL CHECK(status IN ('waiting','excluded','attempted','skipped')),
    reason_code TEXT,
    PRIMARY KEY(social_turn_id, character_id)
);

CREATE TABLE social_triggers (
    input_batch_id TEXT PRIMARY KEY NOT NULL REFERENCES input_batches(input_batch_id),
    chain_id TEXT NOT NULL REFERENCES social_chains(chain_id),
    origin_turn_id TEXT NOT NULL REFERENCES social_turns(social_turn_id),
    status TEXT NOT NULL CHECK(status IN ('pending','consumed','discarded')),
    reason_code TEXT,
    created_at_utc TEXT NOT NULL
);
CREATE INDEX triggers_pending ON social_triggers(chain_id) WHERE status = 'pending';
