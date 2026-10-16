import sqlite3

from echo_games.contracts import (
    ActionReceipt,
    GameEvent,
    GameListQuery,
    GameOperationReceipt,
    OpenOpportunity,
)
from echo_games.domain import Game, Participation
from echo_games.errors import GameError
from echo_games.registry import GameRegistry, RegisteredDefinition


class GameRepository:
    def __init__(self, registry: GameRegistry) -> None:
        self.registry = registry

    def _definition(self, connection: sqlite3.Connection, game_id: str) -> RegisteredDefinition:
        row = connection.execute(
            "SELECT game_type,ruleset_id,ruleset_version FROM game_games WHERE game_id=?",
            (game_id,),
        ).fetchone()
        if row is None:
            raise GameError("game_not_found", "Game does not exist")
        return self.registry.resolve(*row)

    def game(self, connection: sqlite3.Connection, game_id: str) -> Game:
        row = connection.execute(
            "SELECT document FROM game_games WHERE game_id=?", (game_id,)
        ).fetchone()
        if row is None:
            raise GameError("game_not_found", "Game does not exist")
        return self._definition(connection, game_id).models.game.model_validate_json(row[0])

    def insert_game(self, connection: sqlite3.Connection, game: Game, seats: tuple[str, ...]):
        connection.execute(
            "INSERT INTO game_games VALUES (?,?,?,?,?,?,?,?)",
            (
                game.game_id,
                game.game_type,
                game.ruleset_id,
                game.ruleset_version,
                game.creator_ref,
                game.status,
                game.state_version,
                game.model_dump_json(),
            ),
        )
        connection.executemany(
            "INSERT INTO game_seats VALUES (?,?)", ((game.game_id, seat) for seat in seats)
        )

    def save_game(self, connection: sqlite3.Connection, game: Game) -> None:
        connection.execute(
            "UPDATE game_games SET status=?,state_version=?,document=? WHERE game_id=?",
            (game.status, game.state_version, game.model_dump_json(), game.game_id),
        )

    def seats(self, connection: sqlite3.Connection, game_id: str) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in connection.execute(
                "SELECT seat_id FROM game_seats WHERE game_id=? ORDER BY seat_id", (game_id,)
            )
        )

    def participations(
        self, connection: sqlite3.Connection, game_id: str
    ) -> tuple[Participation, ...]:
        return tuple(
            Participation.model_validate_json(row[0])
            for row in connection.execute(
                "SELECT document FROM game_participations WHERE game_id=? "
                "ORDER BY joined_state_version,participation_id",
                (game_id,),
            )
        )

    def insert_participation(self, connection: sqlite3.Connection, item: Participation) -> None:
        connection.execute(
            "INSERT INTO game_participations VALUES (?,?,?,?,?,?,?,?)",
            (
                item.participation_id,
                item.game_id,
                item.seat_id,
                item.participant_ref,
                item.joined_state_version,
                item.left_state_version,
                item.started_state_version,
                item.model_dump_json(),
            ),
        )

    def save_participation(self, connection: sqlite3.Connection, item: Participation) -> None:
        connection.execute(
            "UPDATE game_participations SET left_state_version=?,started_state_version=?,"
            "document=? WHERE participation_id=?",
            (
                item.left_state_version,
                item.started_state_version,
                item.model_dump_json(),
                item.participation_id,
            ),
        )

    def list_games(self, connection: sqlite3.Connection, query: GameListQuery) -> tuple[Game, ...]:
        if not query.game_ids:
            return ()
        placeholders = ",".join("?" for _ in query.game_ids)
        sql = (
            "SELECT game_type,ruleset_id,ruleset_version,document FROM game_games "
            f"WHERE game_id IN ({placeholders}) AND game_id>?"
        )
        values: list = [*query.game_ids, query.after_game_id]
        if query.game_type is not None:
            sql += " AND game_type=?"
            values.append(query.game_type)
        if query.status is not None:
            sql += " AND status=?"
            values.append(query.status)
        sql += " ORDER BY game_id LIMIT ?"
        values.append(query.limit + 1)
        return tuple(
            self.registry.resolve(row[0], row[1], row[2]).models.game.model_validate_json(row[3])
            for row in connection.execute(sql, values)
        )

    def operation(
        self,
        connection: sqlite3.Connection,
        requester_ref: str,
        request_id: str,
        game_id: str | None,
    ) -> tuple[str, GameOperationReceipt] | None:
        values: tuple[str, ...]
        if game_id is None:
            where, values = "operation='create'", (requester_ref, request_id)
        else:
            where, values = "game_id=?", (requester_ref, request_id, game_id)
        row = connection.execute(
            "SELECT command,document,game_id FROM game_operation_receipts "
            f"WHERE requester_ref=? AND request_id=? AND {where}",
            values,
        ).fetchone()
        if row is None:
            return None
        models = self._definition(connection, row[2]).models
        return row[0], models.operation_receipt.model_validate_json(row[1])

    def insert_operation(
        self, connection: sqlite3.Connection, command: str, receipt: GameOperationReceipt
    ) -> None:
        connection.execute(
            "INSERT INTO game_operation_receipts VALUES (?,?,?,?,?,?,?)",
            (
                receipt.receipt_id,
                receipt.game_id,
                receipt.requester_ref,
                receipt.request_id,
                receipt.operation,
                command,
                receipt.model_dump_json(),
            ),
        )

    def action_receipt(
        self, connection: sqlite3.Connection, game_id: str, seat_id: str, request_id: str
    ) -> tuple[str, ActionReceipt] | None:
        row = connection.execute(
            "SELECT command,document FROM game_action_receipts "
            "WHERE game_id=? AND seat_id=? AND request_id=?",
            (game_id, seat_id, request_id),
        ).fetchone()
        if row is None:
            return None
        return row[0], self._definition(
            connection, game_id
        ).models.action_receipt.model_validate_json(row[1])

    def insert_action(
        self, connection: sqlite3.Connection, command: str, receipt: ActionReceipt
    ) -> None:
        connection.execute(
            "INSERT INTO game_action_receipts VALUES (?,?,?,?,?,?,?,?,?)",
            (
                receipt.receipt_id,
                receipt.game_id,
                receipt.seat_id,
                receipt.participant_ref,
                receipt.participation_id,
                receipt.request_id,
                receipt.opportunity_id,
                command,
                receipt.model_dump_json(),
            ),
        )

    def next_sequence(self, connection: sqlite3.Connection, game_id: str) -> int:
        return connection.execute(
            "SELECT COALESCE(MAX(sequence),0)+1 FROM game_events WHERE game_id=?", (game_id,)
        ).fetchone()[0]

    def insert_event(
        self, connection: sqlite3.Connection, event: GameEvent, audience: tuple[str, ...]
    ) -> None:
        connection.execute(
            "INSERT INTO game_events VALUES (?,?,?,?,?)",
            (
                event.event_id,
                event.game_id,
                event.sequence,
                event.state_version,
                event.model_dump_json(),
            ),
        )
        connection.executemany(
            "INSERT INTO game_event_audiences VALUES (?,?,?)",
            ((event.game_id, event.event_id, participation_id) for participation_id in audience),
        )

    def events(
        self,
        connection: sqlite3.Connection,
        game_id: str,
        after_sequence: int,
        limit: int,
        through_state_version: int,
    ) -> tuple[GameEvent, ...]:
        models = self._definition(connection, game_id).models
        return tuple(
            models.event.model_validate_json(row[0])
            for row in connection.execute(
                "SELECT document FROM game_events WHERE game_id=? AND sequence>? "
                "AND state_version<=? ORDER BY sequence LIMIT ?",
                (game_id, after_sequence, through_state_version, limit + 1),
            )
        )

    def event_visible(
        self, connection: sqlite3.Connection, event_id: str, participation_id: str
    ) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM game_event_audiences WHERE event_id=? AND participation_id=?",
                (event_id, participation_id),
            ).fetchone()
            is not None
        )

    def add_opportunity(self, connection: sqlite3.Connection, item: OpenOpportunity) -> None:
        connection.execute(
            "INSERT INTO game_opportunities VALUES (?,?,?,?,?,?, 'open')",
            (
                item.opportunity_id,
                item.game_id,
                item.seat_id,
                item.participation_id,
                item.expected_state_version,
                item.phase,
            ),
        )

    def close_opportunities(self, connection: sqlite3.Connection, game_id: str, status: str):
        connection.execute(
            "UPDATE game_opportunities SET status=? WHERE game_id=? AND status='open'",
            (status, game_id),
        )

    def open_opportunities(
        self, connection: sqlite3.Connection, game_id: str
    ) -> tuple[OpenOpportunity, ...]:
        return tuple(
            OpenOpportunity(
                opportunity_id=row[0],
                game_id=row[1],
                seat_id=row[2],
                participation_id=row[3],
                expected_state_version=row[4],
                phase=row[5],
            )
            for row in connection.execute(
                "SELECT opportunity_id,game_id,seat_id,participation_id,state_version,phase "
                "FROM game_opportunities WHERE game_id=? AND status='open' ORDER BY seat_id",
                (game_id,),
            )
        )
