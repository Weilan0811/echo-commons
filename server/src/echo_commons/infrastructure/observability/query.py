import json
import sqlite3

from echo_commons.infrastructure.database.connection import Database


def read_traces(
    connection: sqlite3.Connection, correlation_id: str
) -> tuple[dict[str, object], ...]:
    rows = connection.execute(
        "SELECT trace_id,kind,entity_type,entity_id,payload_json,created_at_utc, "
        "'delivered' AS delivery_status,NULL AS last_error_code FROM traces "
        "WHERE correlation_id = ? "
        "UNION ALL SELECT trace_id,kind,entity_type,entity_id,payload_json,created_at_utc, "
        "status AS delivery_status,last_error_code FROM trace_outbox WHERE correlation_id = ? "
        "ORDER BY created_at_utc,trace_id",
        (correlation_id, correlation_id),
    )
    result = []
    for row in rows:
        item = dict(row)
        item["payload"] = json.loads(item.pop("payload_json"))
        result.append(item)
    return tuple(result)


class TraceQuery:
    def __init__(self, database: Database) -> None:
        self.database = database

    def read(self, correlation_id: str) -> tuple[dict[str, object], ...]:
        with self.database.read() as connection:
            return read_traces(connection, correlation_id)
