-- Runtime lease fencing.  The generation changes on every successful claim so
-- a delayed result from an older lease cannot mutate a later attempt.

ALTER TABLE conversation_tasks
ADD COLUMN lease_generation INTEGER NOT NULL DEFAULT 0
CHECK(lease_generation >= 0);
