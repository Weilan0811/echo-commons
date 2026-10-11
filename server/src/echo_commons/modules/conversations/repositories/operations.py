import json
import sqlite3

from echo_commons.modules.conversations.operations import (
    ArchiveOperation,
    ArchiveResult,
    ListPreferenceOperation,
    ListPreferenceResult,
    MembershipOperation,
    MembershipResult,
)
from echo_commons.shared.errors import IdempotencyConflict


class ConversationOperationRepository:
    def previous(
        self,
        connection: sqlite3.Connection,
        scope: str,
        operation_id: str,
        request: MembershipOperation | ArchiveOperation | ListPreferenceOperation,
    ) -> MembershipResult | ArchiveResult | ListPreferenceResult | None:
        row = connection.execute(
            "SELECT request_json,result_json FROM conversation_operations "
            "WHERE operation_scope=? AND client_operation_id=?",
            (scope, operation_id),
        ).fetchone()
        if row is None:
            return None
        if json.loads(row["request_json"]) != request.model_dump(mode="json"):
            raise IdempotencyConflict("Client operation ID already has different content")
        result_type = {
            MembershipOperation: MembershipResult,
            ArchiveOperation: ArchiveResult,
            ListPreferenceOperation: ListPreferenceResult,
        }[type(request)]
        return result_type.model_validate_json(row["result_json"])

    def add(
        self,
        connection: sqlite3.Connection,
        scope: str,
        operation_id: str,
        request: MembershipOperation | ArchiveOperation | ListPreferenceOperation,
        result: MembershipResult | ArchiveResult | ListPreferenceResult,
        now: str,
    ) -> None:
        connection.execute(
            "INSERT INTO conversation_operations VALUES (?,?,?,?,?,?)",
            (
                scope,
                operation_id,
                request.conversation_id,
                request.model_dump_json(),
                result.model_dump_json(),
                now,
            ),
        )
