from __future__ import annotations

import json
import sqlite3
from datetime import datetime

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
