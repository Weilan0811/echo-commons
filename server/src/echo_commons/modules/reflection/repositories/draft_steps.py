import sqlite3

from echo_commons.execution.contracts import TaskLease
from echo_commons.infrastructure.database.mapping import utc_text


class DraftStepRepository:
    def latest_writer(self, connection: sqlite3.Connection, lease: TaskLease):
        return connection.execute(
            "SELECT * FROM reflection_draft_steps WHERE node_task_id=? "
            "AND execution_generation=? AND phase='writer' "
            "AND json_extract(result_json,'$.status')='completed' ORDER BY step_id DESC LIMIT 1",
            (lease.task_id, lease.graph_execution_generation),
        ).fetchone()

    def report(self, connection: sqlite3.Connection, draft_step_id: int):
        return connection.execute(
            "SELECT * FROM reflection_draft_steps WHERE draft_step_id=? "
            "AND report_json IS NOT NULL ORDER BY step_id DESC LIMIT 1",
            (draft_step_id,),
        ).fetchone()

    def history(self, connection: sqlite3.Connection, lease: TaskLease):
        return connection.execute(
            "SELECT w.result_json,d.report_json FROM reflection_draft_steps w "
            "JOIN reflection_draft_steps d ON d.draft_step_id=w.step_id "
            "WHERE w.node_task_id=? AND w.execution_generation=? AND d.report_json IS NOT NULL "
            "AND json_extract(d.report_json,'$.passed')=0 ORDER BY d.step_id",
            (lease.task_id, lease.graph_execution_generation),
        ).fetchall()

    def start(
        self,
        connection,
        lease,
        revision,
        phase,
        invocation_id,
        request_json,
        now,
        *,
        draft_step_id=None,
    ):
        cursor = connection.execute(
            "INSERT INTO reflection_draft_steps(node_task_id,execution_generation,attempt,"
            "revision,phase,draft_step_id,invocation_id,request_json,created_at_utc) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                lease.task_id,
                lease.graph_execution_generation,
                lease.attempt,
                revision,
                phase,
                draft_step_id,
                str(invocation_id),
                request_json,
                utc_text(now),
            ),
        )
        return cursor.lastrowid

    def finish(
        self,
        connection,
        step_id,
        now,
        *,
        result_json=None,
        report_json=None,
        error_code=None,
        duration_ms=0,
    ):
        connection.execute(
            "UPDATE reflection_draft_steps SET result_json=?,report_json=?,error_code=?,"
            "duration_ms=?,finished_at_utc=? WHERE step_id=?",
            (result_json, report_json, error_code, duration_ms, utc_text(now), step_id),
        )
