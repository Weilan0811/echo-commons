from __future__ import annotations

import json
import sqlite3
from datetime import datetime, timedelta

from echo_commons.infrastructure.database.mapping import utc_text


def enqueue_trace(
    connection: sqlite3.Connection,
    trace_id: str,
    correlation_id: str,
    kind: str,
    entity_type: str,
    entity_id: str,
    payload: dict[str, object],
    now: datetime,
) -> None:
    connection.execute(
        "INSERT INTO trace_outbox (trace_id, correlation_id, kind, entity_type, "
        "entity_id, payload_json, created_at_utc, available_at_utc) "
        "VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
        (
            trace_id,
            correlation_id,
            kind,
            entity_type,
            entity_id,
            json.dumps(payload, ensure_ascii=False),
            utc_text(now),
            utc_text(now),
        ),
    )


def claim_traces(
    connection: sqlite3.Connection,
    owner: str,
    now: datetime,
    lease_seconds: float,
    max_attempts: int,
    batch_size: int,
) -> tuple[str, ...]:
    connection.execute(
        "UPDATE trace_outbox SET status = CASE WHEN attempt_count >= ? THEN 'failed' "
        "ELSE 'pending' END, lease_owner = NULL, lease_until_utc = NULL, "
        "last_error_code = 'lease_expired' "
        "WHERE status = 'processing' AND lease_until_utc <= ?",
        (max_attempts, utc_text(now)),
    )
    traces = tuple(
        row[0]
        for row in connection.execute(
            "SELECT trace_id FROM trace_outbox WHERE status = 'pending' AND available_at_utc <= ? "
            "ORDER BY created_at_utc, trace_id LIMIT ?",
            (utc_text(now), batch_size),
        )
    )
    for trace_id in traces:
        connection.execute(
            "UPDATE trace_outbox SET status = 'processing', attempt_count = attempt_count + 1, "
            "lease_owner = ?, lease_until_utc = ? WHERE trace_id = ?",
            (owner, utc_text(now + timedelta(seconds=lease_seconds)), trace_id),
        )
    return traces


def deliver_trace(connection: sqlite3.Connection, trace_id: str, owner: str, now: datetime) -> int:
    changed = connection.execute(
        "INSERT INTO traces SELECT trace_id, correlation_id, kind, entity_type, entity_id, "
        "payload_json, created_at_utc FROM trace_outbox WHERE trace_id = ? "
        "AND status = 'processing' "
        "AND lease_owner = ? AND lease_until_utc > ? ON CONFLICT(trace_id) DO NOTHING",
        (trace_id, owner, utc_text(now)),
    ).rowcount
    connection.execute(
        "DELETE FROM trace_outbox WHERE trace_id = ? AND status = 'processing' "
        "AND lease_owner = ? AND lease_until_utc > ?",
        (trace_id, owner, utc_text(now)),
    )
    return changed


def fail_trace(
    connection: sqlite3.Connection,
    trace_id: str,
    owner: str,
    now: datetime,
    code: str,
    max_attempts: int,
    backoff_seconds: float,
) -> None:
    row = connection.execute(
        "SELECT attempt_count FROM trace_outbox WHERE trace_id = ? AND status = 'processing' "
        "AND lease_owner = ? AND lease_until_utc > ?",
        (trace_id, owner, utc_text(now)),
    ).fetchone()
    if row is None:
        return
    failed = row[0] >= max_attempts
    connection.execute(
        "UPDATE trace_outbox SET status = ?, lease_owner = NULL, lease_until_utc = NULL, "
        "last_error_code = ?, available_at_utc = ? WHERE trace_id = ? AND lease_owner = ?",
        (
            "failed" if failed else "pending",
            code,
            utc_text(now + timedelta(seconds=backoff_seconds * 2 ** (row[0] - 1))),
            trace_id,
            owner,
        ),
    )
