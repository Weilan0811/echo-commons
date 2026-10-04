import sqlite3

from echo_commons.execution.observations import ExecutionEventPayload
from echo_commons.execution.recovery import AppliedRecovery
from echo_commons.shared.management import PageOptions, read_page


class ExecutionRecordRepository:
    def add(
        self, connection: sqlite3.Connection, identity: dict, payload: ExecutionEventPayload
    ) -> None:
        columns = tuple(identity)
        connection.execute(
            f"INSERT INTO task_execution_events ({','.join(columns)},payload_json) "
            f"VALUES ({','.join('?' for _ in columns)},?)",
            (*identity.values(), payload.model_dump_json()),
        )

    def latest(
        self, connection: sqlite3.Connection, kind: str, task_id: str, generation: int | None = None
    ) -> AppliedRecovery | None:
        sql = (
            "SELECT payload_json FROM task_execution_events WHERE task_kind=? AND task_id=? "
            "AND event_kind='recovery_applied'"
        )
        parameters = (kind, task_id)
        if generation is not None:
            sql += " AND graph_execution_generation=?"
            parameters = (*parameters, generation)
        row = connection.execute(sql + " ORDER BY event_id DESC LIMIT 1", parameters).fetchone()
        return ExecutionEventPayload.model_validate_json(row[0]).recovery if row else None

    def history(
        self,
        connection: sqlite3.Connection,
        kind: str,
        task_id: str,
        community_id: str,
        character_id: str,
        options: PageOptions,
        graph_run_id: str | None = None,
    ) -> dict:
        page = read_page(
            connection,
            "SELECT * FROM task_execution_events WHERE task_kind=? AND task_id=? "
            "AND community_id=? AND character_id=? AND graph_run_id IS ?",
            (kind, task_id, community_id, character_id, graph_run_id),
            scope={
                "query": "execution_history",
                "kind": kind,
                "task_id": task_id,
                "community_id": community_id,
                "character_id": character_id,
                "graph_run_id": graph_run_id,
            },
            order=("event_id",),
            options=options,
        )
        for item in page["items"]:
            item["payload"] = ExecutionEventPayload.model_validate_json(item.pop("payload_json"))
        return page

    def summary(
        self,
        connection: sqlite3.Connection,
        kind: str,
        task_id: str,
        state: str,
        generation: int | None = None,
    ) -> dict:
        applied = self.latest(connection, kind, task_id, generation)
        return {
            "last_failure": applied.decision.failure if applied else None,
            "last_recovery_action": applied.action if applied else None,
            "next_attempt_at_utc": applied.next_attempt_at_utc
            if applied and state == "retry_wait"
            else None,
            "retry_exhausted": applied.retry_exhausted if applied else None,
        }
