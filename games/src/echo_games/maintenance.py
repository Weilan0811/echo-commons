import sqlite3

from echo_games.service import require_transaction

GAME_TABLES = (
    "game_games",
    "game_seats",
    "game_participations",
    "game_opportunities",
    "game_events",
    "game_event_audiences",
    "game_operation_receipts",
    "game_action_receipts",
)


class GameCleanup:
    def count_records(
        self, connection: sqlite3.Connection, game_ids: tuple[str, ...]
    ) -> dict[str, int]:
        require_transaction(connection)
        if not game_ids:
            return dict.fromkeys(GAME_TABLES, 0)
        placeholders = ",".join("?" for _ in game_ids)
        return {
            table: connection.execute(
                f"SELECT COUNT(*) FROM {table} WHERE game_id IN ({placeholders})", game_ids
            ).fetchone()[0]
            for table in GAME_TABLES
        }

    def delete_records(self, connection: sqlite3.Connection, game_ids: tuple[str, ...]) -> None:
        require_transaction(connection)
        if not game_ids:
            return
        placeholders = ",".join("?" for _ in game_ids)
        for table in reversed(GAME_TABLES):
            connection.execute(f"DELETE FROM {table} WHERE game_id IN ({placeholders})", game_ids)
