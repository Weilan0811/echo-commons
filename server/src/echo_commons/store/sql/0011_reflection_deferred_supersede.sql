-- Allow a newer source version to supersede a deferred Reflection task.
--
-- A deferred task is intentionally not claimable.  Keeping it in the active
-- window uniqueness index would prevent the corrected source window from
-- receiving a new idempotency key after a stale-context decision.
DROP INDEX IF EXISTS uq_reflection_active_window;

CREATE UNIQUE INDEX IF NOT EXISTS uq_reflection_runnable_window
ON reflection_tasks(
    account_id,
    character_id,
    target_agent_id,
    branch,
    IFNULL(window_type, ''),
    window_ref
)
WHERE status IN ('pending', 'processing', 'retry_wait');
