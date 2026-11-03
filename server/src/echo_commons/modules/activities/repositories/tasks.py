from datetime import timedelta
from uuid import uuid4

from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.lease import LeaseLostError
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.activities.domain.task import task_view
from echo_commons.shared.errors import NotFoundError


class ActivityTasks:
    table = "activity_tasks"

    @staticmethod
    def kind(row):
        return f"activity_{row['purpose']}"

    def get(self, connection, task_id):
        row = connection.execute(
            "SELECT * FROM activity_tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("Activity task does not exist")
        return row

    def active(self, connection, scope):
        return connection.execute(
            "SELECT * FROM activity_tasks WHERE game_id=? AND participation_id=? "
            "AND status IN ('pending','processing','retry_wait','suspended') "
            "ORDER BY created_at_utc,task_id LIMIT 1",
            (scope.game_id, scope.participation_id),
        ).fetchone()

    def frozen(self, connection, row):
        return (
            connection.execute(
                "SELECT 1 FROM activity_inputs WHERE input_id=?", (row["input_id"],)
            ).fetchone()
            is not None
        )

    def add(
        self,
        connection,
        scope,
        view,
        opportunity,
        mode,
        model_profile,
        request,
        now,
        *,
        purpose="turn",
        identity=None,
        state_version=None,
    ):
        opportunity_id = opportunity.opportunity_id if opportunity else None
        existing = connection.execute(
            "SELECT task_id FROM activity_tasks "
            "WHERE game_id=? AND participation_id=? AND opportunity_id=? "
            "AND status NOT IN ('failed','cancelled')",
            (scope.game_id, scope.participation_id, opportunity_id),
        ).fetchone()
        if existing:
            return existing[0]
        identity = identity or str(uuid4())
        connection.execute(
            "INSERT INTO activity_tasks(task_id,community_id,character_id,game_id,participation_id,"
            "conversation_id,membership_id,opportunity_id,state_version,view_json,input_id,re"
            "quest_id,"
            "mode,model_profile,decision_request_json,status,available_at_utc,"
            "created_at_utc,updated_at_utc,trace_id,purpose) "
            "VALUES (?,?,?,?,?,?,?,?,?,?,?,?,?,?,?,'pending',?,?,?,?,?)",
            (
                identity,
                scope.community_id,
                scope.character_id,
                scope.game_id,
                scope.participation_id,
                scope.conversation_id,
                scope.membership_id,
                opportunity_id,
                view.state_version if view else state_version,
                view.model_dump_json() if view else None,
                str(uuid4()),
                f"activity:{identity}",
                mode,
                model_profile,
                request.model_dump_json() if request else None,
                utc_text(now),
                utc_text(now),
                utc_text(now),
                str(request.trace_id) if request else str(uuid4()),
                purpose,
            ),
        )
        return identity

    def owned(self, connection, lease, now):
        return connection.execute(
            f"SELECT * FROM {self.table} WHERE task_id=? AND status='processing' "
            "AND attempt_count=? AND lease_generation=? AND lease_owner=? AND lease_until_utc>?",
            (lease.task_id, lease.attempt, lease.generation, lease.owner, utc_text(now)),
        ).fetchone()

    def claim(self, connection, owner, now, seconds):
        row = connection.execute(
            "SELECT t.* FROM activity_tasks t JOIN communities c USING(community_id) "
            "JOIN conversations v USING(conversation_id) "
            "JOIN conversation_memberships m USING(membership_id) "
            "WHERE t.status IN ('pending','retry_wait') AND t.available_at_utc<=? "
            "AND c.status='active' AND v.status='active' AND m.left_at_utc IS NULL "
            "AND NOT EXISTS (SELECT 1 FROM activity_tasks other WHERE other.game_id=t.game_id "
            "AND other.participation_id=t.participation_id AND other.status='processing') "
            "AND NOT EXISTS (SELECT 1 FROM conversation_tasks old WHERE "
            "old.conversation_id=t.conversation_id AND old.character_id=t.character_id "
            "AND old.status IN ('pending','processing','retry_wait','suspended')) "
            "AND NOT EXISTS (SELECT 1 FROM activity_expression_tasks e JOIN activity_results "
            "r ON r.result_id=e.task_id "
            "JOIN activity_tasks a ON a.task_id=r.task_id WHERE a.game_id=t.game_id "
            "AND a.participation_id=t.participation_id AND e.status='processing') "
            "ORDER BY t.available_at_utc,t.created_at_utc,t.task_id LIMIT 1",
            (utc_text(now),),
        ).fetchone()
        if row is None:
            return None
        expiry = now + timedelta(seconds=seconds)
        connection.execute(
            "UPDATE activity_tasks SET status='processing',attempt_count=attempt_count+1,"
            "lease_generation=lease_generation+1,lease_owner=?,lease_until_utc=?,"
            "updated_at_utc=? WHERE task_id=?",
            (owner, utc_text(expiry), utc_text(now), row["task_id"]),
        )
        return TaskLease(
            row["task_id"],
            f"activity_{row['purpose']}",
            row["attempt_count"] + 1,
            row["lease_generation"] + 1,
            owner,
            expiry,
            row["trace_id"],
        )

    def release(self, connection, task_id, state, now, available_at, code=None):
        connection.execute(
            f"UPDATE {self.table} SET status=?,lease_owner=NULL,lease_until_utc=NULL,"
            "available_at_utc=?,last_error_code=?,updated_at_utc=? WHERE task_id=?",
            (state, utc_text(available_at), code, utc_text(now), task_id),
        )

    def save_stage(self, connection, lease, column, content, now):
        if column not in (
            "prepared_json",
            "decision_request_json",
            "decision_response_json",
            "last_invocation_json",
            "last_run_json",
            "input_json",
        ):
            raise ValueError("Unknown activity execution stage")
        if self.owned(connection, lease, now) is None:
            raise LeaseLostError("Activity task lease is no longer owned")
        connection.execute(
            f"UPDATE {self.table} SET {column}=? WHERE task_id=?", (content, lease.task_id)
        )

    def definition(self, row, games):
        view = task_view(row)
        return games.registry.resolve(view.game_type, view.ruleset_id, view.ruleset_version)
