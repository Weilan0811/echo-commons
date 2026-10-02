import sqlite3
from uuid import UUID

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.reflection.domain.result import GraphReviewRecord


class ResultRepository:
    def for_graph(
        self, connection: sqlite3.Connection, graph_run_id: str
    ) -> GraphReviewRecord | None:
        row = connection.execute(
            "SELECT * FROM reflection_graph_results WHERE graph_run_id = ?", (graph_run_id,)
        ).fetchone()
        if row is None:
            return None
        return GraphReviewRecord(
            UUID(row["result_id"]),
            UUID(row["graph_run_id"]),
            row["aggregate_fingerprint"],
            row["payload_json"],
            utc_datetime(row["created_at_utc"]),
            row["status"],
            row["decision_code"],
            utc_datetime(row["decided_at_utc"]) if row["decided_at_utc"] else None,
        )

    def add(self, connection: sqlite3.Connection, result: GraphReviewRecord) -> None:
        connection.execute(
            "INSERT INTO reflection_graph_results VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(result.result_id),
                str(result.graph_run_id),
                result.aggregate_fingerprint,
                result.payload_json,
                result.status.value,
                result.decision_code,
                utc_text(result.created_at_utc),
                utc_text(result.decided_at_utc) if result.decided_at_utc else None,
            ),
        )
