from datetime import timedelta

from echo_commons.execution.contracts import TaskLease
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.activities.repositories.tasks import ActivityTasks
from echo_commons.shared.errors import NotFoundError


class ExpressionTasks(ActivityTasks):
    table = "activity_expression_tasks"

    @staticmethod
    def kind(row):
        return "activity_expression"

    def get(self, connection, task_id):
        row = connection.execute(
            "SELECT e.*,t.task_id AS parent_task_id,t.community_id,t.character_id,t.game_id,"
            "t.participation_id,t.conversation_id,t.membership_id,t.input_id,t.trace_id,"
            "'expression' AS purpose,r.expression_json,r.receipt_json,r.publication_status "
            "FROM activity_expression_tasks e JOIN activity_results r ON r.result_id=e.task_id "
            "JOIN activity_tasks t ON t.task_id=r.task_id WHERE e.task_id=?",
            (task_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("Activity expression does not exist")
        return row

    def owned(self, connection, lease, now):
        return (
            self.get(connection, lease.task_id) if super().owned(connection, lease, now) else None
        )

    def enqueue(self, connection, result_id, now):
        connection.execute(
            "INSERT INTO activity_expression_tasks(task_id,status,available_at_utc,created_at"
            "_utc,updated_at_utc) "
            "VALUES (?,'pending',?,?,?) ON CONFLICT(task_id) DO NOTHING",
            (result_id, utc_text(now), utc_text(now), utc_text(now)),
        )

    def claim(self, connection, owner, now, seconds):
        rows = connection.execute(
            "SELECT e.task_id FROM activity_expression_tasks e JOIN activity_results r ON "
            "r.result_id=e.task_id "
            "JOIN activity_tasks t ON t.task_id=r.task_id WHERE e.status IN "
            "('pending','retry_wait') "
            "AND e.available_at_utc<=? AND e.social_turn_id IS NOT NULL "
            "AND NOT EXISTS (SELECT 1 FROM activity_tasks a WHERE a.game_id=t.game_id "
            "AND a.participation_id=t.participation_id AND (a.status='processing' OR "
            "(a.status IN ('pending','retry_wait') AND e.input_json IS NULL AND EXISTS "
            "(SELECT 1 FROM activity_inputs i WHERE i.input_id=a.input_id)))) "
            "AND NOT EXISTS (SELECT 1 FROM activity_expression_tasks other JOIN "
            "activity_results b ON b.result_id=other.task_id "
            "JOIN activity_tasks a ON a.task_id=b.task_id WHERE a.game_id=t.game_id "
            "AND a.participation_id=t.participation_id AND other.status='processing') "
            "ORDER BY e.available_at_utc,e.created_at_utc,e.task_id LIMIT 1",
            (utc_text(now),),
        ).fetchone()
        if rows is None:
            return None
        row = self.get(connection, rows[0])
        expiry = now + timedelta(seconds=seconds)
        connection.execute(
            "UPDATE activity_expression_tasks SET "
            "status='processing',attempt_count=attempt_count+1,"
            "lease_generation=lease_generation+1,lease_owner=?,lease_until_utc=?,updated_at_u"
            "tc=? WHERE task_id=?",
            (owner, utc_text(expiry), utc_text(now), row["task_id"]),
        )
        return TaskLease(
            row["task_id"],
            "activity_expression",
            row["attempt_count"] + 1,
            row["lease_generation"] + 1,
            owner,
            expiry,
            row["trace_id"],
        )
