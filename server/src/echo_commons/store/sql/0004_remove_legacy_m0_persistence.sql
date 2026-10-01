-- Remove the M0 persistence model after the canonical Conversation Runtime
-- became the only execution path.  Historical migrations remain immutable;
-- this migration is the explicit cleanup boundary for existing databases.

-- Drop dependent tables before the legacy task table because both proposal
-- tables reference conversation_turns.
DROP TABLE IF EXISTS agent_proposals;
DROP TABLE IF EXISTS situation_proposals;
DROP TABLE IF EXISTS conversation_turns;

-- The canonical conversation identity is no longer coupled to one character
-- or to a persisted stage summary.  Participants and future context services
-- own those concerns.
ALTER TABLE conversations DROP COLUMN character_id;
ALTER TABLE conversations DROP COLUMN stage_summary;

-- WorldState is the canonical owner of the authoritative state version.
DELETE FROM meta WHERE key = 'state_version';
