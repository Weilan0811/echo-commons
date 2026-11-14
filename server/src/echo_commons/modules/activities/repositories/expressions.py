from datetime import timedelta

from echo_commons.execution.contracts import SchedulingLane, TaskCandidate, TaskLease, TaskOccupancy
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
            ",t.purpose AS parent_purpose,"
            "json_extract(r.artifact_json,'$.turn_expression.timing') AS expression_timing "
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

    def enqueue(self, connection, result_id, now, *, stage=None, receipt=None):
        connection.execute(
            "INSERT INTO activity_expression_tasks(task_id,status,available_at_utc,created_at"
            "_utc,updated_at_utc) "
            "VALUES (?,'pending',?,?,?) ON CONFLICT(task_id) DO NOTHING",
            (result_id, utc_text(now), utc_text(now), utc_text(now)),
        )
        if stage is not None:
            value = stage.input.model_copy(
                update={
                    "receipt": receipt.model_dump(mode="json"),
                    "receipt_event_ids": receipt.event_ids,
                }
            )
            connection.execute(
                "UPDATE activity_expression_tasks SET input_json=?,prepared_json=? WHERE task_id=?",
                (value.model_dump_json(), stage.proposal.model_dump_json(), result_id),
            )

    @staticmethod
    def candidate(row):
        return TaskCandidate(
            row["task_id"],
            "activity_expression",
            row["available_at_utc"],
            row["created_at_utc"],
            (("public_expression", row["conversation_id"], row["character_id"]),),
        )

    def occupancies(self, connection):
        occupied = []
        for row in connection.execute(
            "SELECT e.task_id,e.status,e.created_at_utc,e.social_turn_id,"
            "t.game_id,t.conversation_id,t.character_id,t.purpose "
            "FROM activity_expression_tasks e JOIN activity_results r ON r.result_id=e.task_id "
            "JOIN activity_tasks t ON t.task_id=r.task_id "
            "WHERE r.publication_status='pending'"
        ):
            scopes = ()
            if row["purpose"] == "turn":
                scopes += (("game_action", row["game_id"]),)
            occupied.append(TaskOccupancy(row["task_id"], "activity_expression", scopes))
            if row["social_turn_id"] and row["status"] in (
                "pending",
                "processing",
                "retry_wait",
                "suspended",
            ):
                occupied.append(
                    TaskOccupancy(
                        row["task_id"],
                        "activity_expression",
                        (("public_expression", row["conversation_id"], row["character_id"]),),
                        None
                        if row["status"] == "processing"
                        else (row["created_at_utc"], "activity_expression", row["task_id"]),
                    )
                )
        return tuple(occupied)

    def waiting_scopes(self, connection):
        return {
            (row["community_id"], row["character_id"]): SchedulingLane.EXCHANGE
            for row in connection.execute(
                "SELECT t.community_id,t.character_id FROM activity_expression_tasks e "
                "JOIN activity_results r ON r.result_id=e.task_id "
                "JOIN activity_tasks t ON t.task_id=r.task_id "
                "JOIN communities c USING(community_id) "
                "WHERE e.status IN ('pending','retry_wait') AND c.status='active' AND "
                "json_extract(e.input_json,'$.material.conversation.memory.context_prepared')=0"
            )
        }

    def candidates(self, connection, now):
        return tuple(
            self.get(connection, row[0])
            for row in connection.execute(
                "SELECT e.task_id FROM activity_expression_tasks e JOIN activity_results r ON "
                "r.result_id=e.task_id "
                "JOIN activity_tasks t ON t.task_id=r.task_id WHERE e.status IN "
                "('pending','retry_wait') "
                "AND e.available_at_utc<=? AND e.social_turn_id IS NOT NULL "
                "AND COALESCE(json_extract(e.input_json,"
                "'$.material.conversation.memory.context_prepared'),1)=1 "
                "ORDER BY e.available_at_utc,e.created_at_utc,e.task_id",
                (utc_text(now),),
            ).fetchall()
        )

    def claim(self, connection, owner, now, seconds, *, task_id=None, allowed=None):
        row = next(
            (
                row
                for row in self.candidates(connection, now)
                if (task_id is None or row["task_id"] == task_id)
                and (allowed is None or allowed(self.candidate(row)))
            ),
            None,
        )
        if row is None:
            return None
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
