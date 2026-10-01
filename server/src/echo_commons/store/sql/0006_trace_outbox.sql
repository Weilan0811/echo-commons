-- Operational Trace delivery queue.  Core Runtime transactions enqueue
-- events here; materialization into the historical traces table is retried
-- separately and must not hold up T1/T2/T3 state commits.

CREATE TABLE IF NOT EXISTS trace_outbox (
    trace_id TEXT PRIMARY KEY,
    correlation_id TEXT NOT NULL,
    kind TEXT NOT NULL,
    entity_type TEXT NOT NULL,
    entity_id TEXT NOT NULL,
    payload_json TEXT NOT NULL,
    created_at_utc TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'pending'
        CHECK(status IN ('pending', 'processing', 'failed')),
    attempt_count INTEGER NOT NULL DEFAULT 0 CHECK(attempt_count >= 0),
    available_at_utc TEXT NOT NULL,
    lease_owner TEXT,
    lease_until_utc TEXT,
    last_error_code TEXT,
    CHECK(
        (status = 'processing' AND lease_owner IS NOT NULL AND lease_until_utc IS NOT NULL)
        OR (status <> 'processing' AND lease_owner IS NULL AND lease_until_utc IS NULL)
    )
);

CREATE INDEX IF NOT EXISTS ix_trace_outbox_claim
ON trace_outbox(status, available_at_utc, created_at_utc, trace_id);
