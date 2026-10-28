CREATE TABLE social_participation_judgments (
    task_id TEXT PRIMARY KEY NOT NULL REFERENCES conversation_tasks(task_id),
    mode TEXT NOT NULL CHECK(mode IN ('ordinary','decision')),
    request_json TEXT CHECK(request_json IS NULL OR json_valid(request_json)),
    timeout_seconds REAL NOT NULL CHECK(timeout_seconds>0),
    choice TEXT CHECK(choice IN ('participate','silent','understand')),
    response_json TEXT CHECK(response_json IS NULL OR json_valid(response_json)),
    decided_at_utc TEXT,
    CHECK((mode='ordinary' AND request_json IS NULL AND choice IS NULL)
       OR (mode='decision' AND request_json IS NOT NULL)),
    CHECK((choice IS NULL AND response_json IS NULL AND decided_at_utc IS NULL)
       OR (choice IS NOT NULL AND response_json IS NOT NULL AND decided_at_utc IS NOT NULL))
);
INSERT INTO social_participation_judgments(task_id,mode,timeout_seconds)
    SELECT task_id,'ordinary',30 FROM conversation_tasks WHERE snapshot_id IS NOT NULL;
