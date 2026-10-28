import json
import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.agents.contracts.output import (
    CHARACTER_EXPRESSION_CONTRACT,
    CHARACTER_MESSAGE_CONTRACT,
    CheckedCharacterExpression,
)
from echo_commons.agents.contracts.run import AgentRunResult
from echo_commons.execution.contracts import TaskLease
from echo_commons.infrastructure.database.mapping import utc_text


class ConversationResultRepository:
    def by_attempt(
        self, connection: sqlite3.Connection, task_id: str, attempt: int
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM conversation_results WHERE task_id = ? AND attempt_no = ?",
            (task_id, attempt),
        ).fetchone()

    def add(
        self,
        connection: sqlite3.Connection,
        lease: TaskLease,
        result: AgentRunResult,
        status: str,
        code: str,
        now: datetime,
    ) -> str:
        result_id = str(uuid4())
        public = result.model_dump(mode="json")
        checked = result.output.payload if result.output is not None else None
        if result.output is not None and result.output.contract == CHARACTER_EXPRESSION_CONTRACT:
            if isinstance(checked, CheckedCharacterExpression):
                public["output"]["payload"] = checked.message.model_dump(mode="json")
            public["output"]["contract"] = CHARACTER_MESSAGE_CONTRACT.model_dump(mode="json")
        if public["output"] is not None:
            public["output"]["payload"].pop("thought", None)
        connection.execute(
            "INSERT INTO conversation_results VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                result_id,
                lease.task_id,
                lease.attempt,
                lease.generation,
                str(result.invocation_id),
                CHARACTER_MESSAGE_CONTRACT.schema_id,
                json.dumps(public, ensure_ascii=False),
                status,
                code,
                utc_text(now),
                utc_text(now),
            ),
        )
        if result.output is not None and result.output.contract == CHARACTER_EXPRESSION_CONTRACT:
            connection.execute(
                "INSERT INTO conversation_claims(result_id,output_contract,claims_json) "
                "VALUES (?,?,?)",
                (
                    result_id,
                    result.output.contract.schema_id,
                    json.dumps(
                        [claim.model_dump(mode="json") for claim in checked.claims]
                        if isinstance(checked, CheckedCharacterExpression)
                        else [],
                        ensure_ascii=False,
                    ),
                ),
            )
        return result_id
