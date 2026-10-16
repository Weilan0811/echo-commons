import sqlite3

from pydantic import BaseModel

from echo_commons.modules.communities.contracts import GameSessionOperationSnapshot
from echo_commons.shared.errors import IdempotencyConflict, NotFoundError


class GameParticipationRepository:
    def find_association(self, connection: sqlite3.Connection, game_id: str) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM community_games WHERE game_id=?", (game_id,)
        ).fetchone()

    def game_ids(self, connection: sqlite3.Connection, community_id: str) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in connection.execute(
                "SELECT game_id FROM community_games WHERE community_id=? ORDER BY game_id",
                (community_id,),
            )
        )

    def association(self, connection: sqlite3.Connection, game_id: str) -> sqlite3.Row:
        row = self.find_association(connection, game_id)
        if row is None:
            raise NotFoundError("Game session does not exist")
        return row

    def for_conversation(
        self, connection: sqlite3.Connection, community_id: str, conversation_id: str
    ) -> str:
        row = connection.execute(
            "SELECT game_id FROM community_games WHERE community_id=? AND conversation_id=?",
            (community_id, conversation_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Conversation has no associated game")
        return row[0]

    def add_association(
        self, connection: sqlite3.Connection, community_id: str, game_id: str, conversation_id: str
    ) -> None:
        connection.execute(
            "INSERT INTO community_games VALUES (?,?,?)", (game_id, community_id, conversation_id)
        )

    def operation(
        self, connection: sqlite3.Connection, requester_ref: str, scope: str, request_id: str
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM game_session_operations "
            "WHERE requester_ref=? AND request_id=? "
            "AND (operation_scope=? OR (operation='create' AND game_id=?))",
            (requester_ref, request_id, scope, scope),
        ).fetchone()

    def previous(
        self,
        connection: sqlite3.Connection,
        requester_ref: str,
        scope: str,
        request_id: str,
        operation: str,
        command: BaseModel,
    ) -> sqlite3.Row | None:
        row = self.operation(connection, requester_ref, scope, request_id)
        if row is not None and (
            row["operation"] != operation or row["request_json"] != command.model_dump_json()
        ):
            raise IdempotencyConflict("Game session request ID already has different content")
        return row

    def add_operation(
        self,
        connection: sqlite3.Connection,
        requester_ref: str,
        scope: str,
        request_id: str,
        community_id: str,
        game_id: str,
        operation: str,
        command: BaseModel,
        snapshot: GameSessionOperationSnapshot,
    ) -> None:
        connection.execute(
            "INSERT INTO game_session_operations VALUES (?,?,?,?,?,?,?,?)",
            (
                scope,
                requester_ref,
                request_id,
                community_id,
                game_id,
                operation,
                command.model_dump_json(),
                snapshot.model_dump_json(),
            ),
        )
