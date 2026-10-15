import json
import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.agents.contracts.output import CHARACTER_MESSAGE_CONTRACT
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
        return result_id
