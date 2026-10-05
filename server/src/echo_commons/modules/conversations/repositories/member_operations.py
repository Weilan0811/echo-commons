import sqlite3

from echo_commons.modules.conversations.member_operations import (
    MembershipOperation,
    MembershipResult,
)
from echo_commons.shared.errors import IdempotencyConflict


class MembershipOperationRepository:
    def previous(
        self,
        connection: sqlite3.Connection,
        scope: str,
        operation_id: str,
        request: MembershipOperation,
    ) -> MembershipResult | None:
        row = connection.execute(
            "SELECT request_json,result_json FROM conversation_membership_operations "
            "WHERE operation_scope=? AND client_operation_id=?",
            (scope, operation_id),
        ).fetchone()
        if row is None:
            return None
        if MembershipOperation.model_validate_json(row["request_json"]) != request:
            raise IdempotencyConflict("Client operation ID already has different content")
        return MembershipResult.model_validate_json(row["result_json"])

    def add(
        self,
        connection: sqlite3.Connection,
        scope: str,
        operation_id: str,
        request: MembershipOperation,
        result: MembershipResult,
        now: str,
    ) -> None:
        connection.execute(
            "INSERT INTO conversation_membership_operations VALUES (?,?,?,?,?,?)",
            (
                scope,
                operation_id,
                request.conversation_id,
                request.model_dump_json(),
                result.model_dump_json(),
                now,
            ),
        )
