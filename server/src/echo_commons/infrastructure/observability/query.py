import json
import sqlite3

from echo_commons.infrastructure.database.connection import Database
from echo_commons.shared.errors import NotFoundError


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

    def scoped(
        self, community_id: str, correlation_id: str, character_id: str | None = None
    ) -> tuple[dict[str, object], ...]:
        with self.database.read() as connection:
            # 从权威对象确定归属，追踪记录自身不承担业务身份认证。
            owners = connection.execute(
                "SELECT character_id,trace_id AS correlation_id FROM conversation_tasks "
                "WHERE community_id = ? "
                "AND trace_id = ? UNION ALL "
                "SELECT character_id,trace_id AS correlation_id FROM reflection_graph_runs "
                "WHERE community_id = ? "
                "AND trace_id = ? UNION ALL "
                "SELECT CASE WHEN sender_kind = 'character' THEN sender_id END AS character_id,"
                "CASE WHEN sender_kind = 'character' THEN trace_id ELSE message_id END "
                "AS correlation_id FROM messages WHERE community_id = ? "
                "AND (trace_id = ? OR message_id = ?)",
                (*(community_id, correlation_id) * 2, community_id, correlation_id, correlation_id),
            ).fetchall()
            if not owners or (
                character_id is not None and not any(row[0] == character_id for row in owners)
            ):
                raise NotFoundError("Trace does not belong to this management scope")
            correlations = {
                row["correlation_id"]
                for row in owners
                if character_id is None or row["character_id"] == character_id
            }
            traces = {
                item["trace_id"]: item
                for identity in correlations
                for item in read_traces(connection, identity)
            }
            return tuple(
                sorted(
                    traces.values(),
                    key=lambda item: (
                        item["created_at_utc"],
                        item["trace_id"],
                    ),
                )
            )
