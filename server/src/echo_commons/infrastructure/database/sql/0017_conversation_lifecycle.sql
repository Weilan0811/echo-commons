ALTER TABLE conversations ADD COLUMN state_version INTEGER NOT NULL DEFAULT 1 CHECK(state_version>=1);
ALTER TABLE conversations ADD COLUMN creator_player_id TEXT REFERENCES players(player_id);
ALTER TABLE conversations ADD COLUMN legacy_small_group INTEGER NOT NULL DEFAULT 0 CHECK(legacy_small_group IN (0,1));

CREATE TABLE direct_conversation_pairs (
    community_id TEXT NOT NULL REFERENCES communities(community_id),
    player_id TEXT NOT NULL REFERENCES players(player_id),
    character_id TEXT NOT NULL REFERENCES character_instances(character_id),
    conversation_id TEXT NOT NULL UNIQUE REFERENCES conversations(conversation_id),
    PRIMARY KEY(community_id,player_id,character_id)
);
CREATE TABLE conversation_list_preferences (
    player_id TEXT NOT NULL REFERENCES players(player_id),
    conversation_id TEXT NOT NULL REFERENCES conversations(conversation_id),
    hidden INTEGER NOT NULL CHECK(hidden IN (0,1)),
    updated_at_utc TEXT NOT NULL,
    PRIMARY KEY(player_id,conversation_id)
);
ALTER TABLE conversation_membership_operations RENAME TO conversation_operations;

INSERT INTO direct_conversation_pairs
SELECT community_id,player_id,character_id,conversation_id FROM (
    SELECT c.community_id,p.actor_id player_id,a.actor_id character_id,c.conversation_id,
        ROW_NUMBER() OVER (PARTITION BY c.community_id,p.actor_id,a.actor_id
            ORDER BY (c.status='active') DESC,c.created_at_utc,c.conversation_id) position
    FROM conversations c
    JOIN (SELECT DISTINCT conversation_id,actor_id FROM conversation_memberships WHERE actor_kind='player') p USING(conversation_id)
    JOIN (SELECT DISTINCT conversation_id,actor_id FROM conversation_memberships WHERE actor_kind='character') a USING(conversation_id)
    WHERE c.kind='direct'
) WHERE position=1;

UPDATE conversations SET legacy_small_group=1 WHERE kind='group' AND
    (SELECT COUNT(*) FROM conversation_memberships m WHERE m.conversation_id=conversations.conversation_id AND joined_at_utc=conversations.created_at_utc AND joined_after_sequence=0)<3;

CREATE TEMP TABLE u08_archived AS
SELECT conversation_id FROM conversations c WHERE status='active' AND (
    (kind='direct' AND NOT EXISTS (SELECT 1 FROM direct_conversation_pairs p WHERE p.conversation_id=c.conversation_id))
    OR (kind='group' AND NOT EXISTS (SELECT 1 FROM conversation_memberships m
        WHERE m.conversation_id=c.conversation_id AND actor_kind='player' AND left_at_utc IS NULL))
);
UPDATE conversations SET status='archived',state_version=state_version+1,
    updated_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE conversation_id IN (SELECT conversation_id FROM u08_archived);
UPDATE input_batches SET status='sealed',sealed_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),
    updated_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE status='collecting' AND conversation_id IN (SELECT conversation_id FROM u08_archived);
UPDATE conversation_tasks SET status='cancelled',lease_owner=NULL,lease_until_utc=NULL,
    lease_generation=lease_generation+1,last_error_code='conversation_archived',
    updated_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE status IN ('pending','processing','retry_wait','suspended')
    AND conversation_id IN (SELECT conversation_id FROM u08_archived);
UPDATE participation_decisions SET status='cancelled',outcome='cancelled',
    updated_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE status='selected' AND social_turn_id IN
    (SELECT social_turn_id FROM social_turns WHERE conversation_id IN (SELECT conversation_id FROM u08_archived));
UPDATE social_candidates SET status='skipped',reason_code='conversation_archived'
WHERE status='waiting' AND social_turn_id IN
    (SELECT social_turn_id FROM social_turns WHERE conversation_id IN (SELECT conversation_id FROM u08_archived));
UPDATE social_turns SET status='cancelled',completion_json=json_object('cancelled',
    (SELECT COUNT(*) FROM participation_decisions p WHERE p.social_turn_id=social_turns.social_turn_id AND p.status='cancelled')),
    completed_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now'),stop_reason='conversation_archived'
WHERE status IN ('pending','running') AND conversation_id IN (SELECT conversation_id FROM u08_archived);
UPDATE social_chains SET status='cancelled',stop_reason='conversation_archived',
    completed_at_utc=strftime('%Y-%m-%dT%H:%M:%f+00:00','now')
WHERE status='active' AND conversation_id IN (SELECT conversation_id FROM u08_archived);
UPDATE social_triggers SET status='discarded' WHERE status='pending' AND chain_id IN
    (SELECT chain_id FROM social_chains WHERE conversation_id IN (SELECT conversation_id FROM u08_archived));
DROP TABLE u08_archived;
