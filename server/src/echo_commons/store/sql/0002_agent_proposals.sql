-- The generic Proposal persistence boundary.  The M0 situation_proposals
-- table from 0001 remains untouched as historical data and is no longer used
-- by Runtime code.
CREATE TABLE IF NOT EXISTS agent_proposals (
    proposal_id TEXT PRIMARY KEY,
    turn_id TEXT NOT NULL REFERENCES conversation_turns(turn_id),
    invocation_id TEXT,
    agent_id TEXT NOT NULL,
    agent_kind TEXT NOT NULL,
    kind TEXT NOT NULL,
    proposal_schema_version TEXT NOT NULL,
    status TEXT NOT NULL CHECK(status IN ('pending', 'approved', 'rejected', 'expired')),
    context_version TEXT NOT NULL,
    target_json TEXT NOT NULL,
    references_json TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    decision_code TEXT,
    source TEXT NOT NULL DEFAULT 'agent_run',
    created_at_utc TEXT NOT NULL,
    decided_at_utc TEXT
);

-- Preserve existing local M0 proposal history without keeping its runtime
-- model alive.  M0 had no invocation id, so those rows remain explicitly
-- marked as legacy and cannot be confused with a new Agent Run.
INSERT INTO agent_proposals(
    proposal_id, turn_id, invocation_id, agent_id, agent_kind, kind,
    proposal_schema_version, status, context_version, target_json,
    references_json, payload_json, decision_code, source, created_at_utc,
    decided_at_utc
)
SELECT
    p.proposal_id,
    p.turn_id,
    NULL,
    p.agent_id,
    'character',
    'character_message',
    'v1',
    p.status,
    p.context_version,
    json_object(
        'conversation_id', t.conversation_id,
        'character_id', c.character_id
    ),
    json_array(t.trigger_message_id),
    json_object(
        'kind', 'character_message',
        'character_id', c.character_id,
        'utterance', p.utterance,
        'reply_to_message_id', t.trigger_message_id
    ),
    p.decision_code,
    'legacy_m0',
    p.created_at_utc,
    p.decided_at_utc
FROM situation_proposals AS p
JOIN conversation_turns AS t ON t.turn_id = p.turn_id
JOIN conversations AS c
  ON c.account_id = t.account_id
 AND c.conversation_id = t.conversation_id;

CREATE INDEX IF NOT EXISTS idx_agent_proposals_turn_status
    ON agent_proposals(turn_id, status);

CREATE INDEX IF NOT EXISTS idx_agent_proposals_invocation
    ON agent_proposals(invocation_id);

CREATE UNIQUE INDEX IF NOT EXISTS uq_agent_proposals_approved_character_message
    ON agent_proposals(turn_id)
    WHERE status = 'approved' AND kind = 'character_message';
