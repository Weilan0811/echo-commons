import sqlite3
from datetime import datetime, timedelta

from echo_commons.execution.contracts import TaskCandidate, TaskLease, TaskOccupancy
from echo_commons.infrastructure.database.mapping import utc_text


class ConversationQueueRepository:
    @staticmethod
    def kind(connection, task_id):
        row = connection.execute(
            "SELECT expression_selected FROM social_willingness_tasks WHERE task_id=?", (task_id,)
        ).fetchone()
        return "social_willingness" if row and not row[0] else "conversation_reply"

    @staticmethod
    def candidate(row):
        return TaskCandidate(
            row["task_id"],
            dict(row).get("task_kind", "conversation_reply"),
            row["available_at_utc"],
            row["created_at_utc"],
            (("public_expression", row["conversation_id"], row["character_id"]),),
        )

    def occupancies(self, connection):
        return tuple(
            TaskOccupancy(
                row["task_id"],
                self.kind(connection, row["task_id"]),
                self.candidate(row).required_scopes,
                None
                if row["status"] == "processing"
                else (row["created_at_utc"], "conversation_reply", row["task_id"]),
            )
            for row in connection.execute(
                "SELECT t.* FROM conversation_tasks t JOIN social_turns s USING(social_turn_id) "
                "WHERE t.status='processing' OR (s.status='running' AND "
                "t.status IN ('pending','retry_wait','suspended'))"
            )
        )

    def candidates(self, connection, now):
        return tuple(
            connection.execute(
                "SELECT t.*,CASE WHEN j.task_id IS NOT NULL AND j.expression_selected=0 "
                "THEN 'social_willingness' ELSE 'conversation_reply' END AS task_kind "
                "FROM conversation_tasks t LEFT JOIN social_willingness_tasks j USING(task_id) "
                "JOIN communities c USING(community_id) "
                "JOIN conversations v USING(conversation_id) "
                "JOIN conversation_memberships m USING(membership_id) "
                "JOIN social_turns s ON s.social_turn_id=t.social_turn_id "
                "LEFT JOIN social_chains ch ON ch.chain_id=s.chain_id "
                "WHERE t.status IN ('pending','retry_wait') AND t.available_at_utc <= ? "
                "AND c.status = 'active' AND v.status = 'active' AND m.left_at_utc IS NULL "
                "AND s.status='running' AND (ch.chain_id IS NULL OR ch.status='active') "
                "AND t.snapshot_id IS NOT NULL "
                "AND COALESCE(json_extract(t.snapshot_json,'$.memory.retrieval_prepared'),1)=1 "
                "AND COALESCE(json_extract(t.snapshot_json,'$.memory.context_prepared'),1)=1 "
                "ORDER BY t.available_at_utc, t.created_at_utc, t.task_id",
                (utc_text(now),),
            )
        )

    def claim(
        self,
        connection: sqlite3.Connection,
        owner: str,
        now: datetime,
        lease_seconds: float,
        *,
        task_id=None,
        allowed=None,
    ) -> TaskLease | None:
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
        expiry = now + timedelta(seconds=lease_seconds)
        connection.execute(
            "UPDATE conversation_tasks SET status = 'processing', "
            "attempt_count = attempt_count + 1, "
            "lease_generation = lease_generation + 1, lease_owner = ?, lease_until_utc = ?, "
            "updated_at_utc = ? WHERE task_id = ?",
            (owner, utc_text(expiry), utc_text(now), row["task_id"]),
        )
        return TaskLease(
            row["task_id"],
            self.kind(connection, row["task_id"]),
            row["attempt_count"] + 1,
            row["lease_generation"] + 1,
            owner,
            expiry,
            row["trace_id"],
        )

    def owned(
        self, connection: sqlite3.Connection, lease: TaskLease, now: datetime
    ) -> sqlite3.Row | None:
        return connection.execute(
            "SELECT * FROM conversation_tasks WHERE task_id = ? AND status = 'processing' "
            "AND attempt_count = ? AND lease_generation = ? "
            "AND lease_owner = ? AND lease_until_utc > ?",
            (lease.task_id, lease.attempt, lease.generation, lease.owner, utc_text(now)),
        ).fetchone()

    def renew(
        self, connection: sqlite3.Connection, lease: TaskLease, now: datetime, seconds: float
    ) -> bool:
        if self.owned(connection, lease, now) is None:
            return False
        connection.execute(
            "UPDATE conversation_tasks SET lease_until_utc = ?, updated_at_utc = ? "
            "WHERE task_id = ?",
            (utc_text(now + timedelta(seconds=seconds)), utc_text(now), lease.task_id),
        )
        return True

    def expired(self, connection: sqlite3.Connection, now: datetime) -> tuple[sqlite3.Row, ...]:
        return tuple(
            connection.execute(
                "SELECT * FROM conversation_tasks WHERE status = 'processing' "
                "AND lease_until_utc <= ?",
                (utc_text(now),),
            )
        )

    def release(
        self,
        connection: sqlite3.Connection,
        task_id: str,
        status: str,
        now: datetime,
        available_at: datetime,
        error_code: str | None,
    ) -> None:
        connection.execute(
            "UPDATE conversation_tasks SET status = ?, lease_owner = NULL, lease_until_utc = NULL, "
            "available_at_utc = ?, last_error_code = ?, updated_at_utc = ? WHERE task_id = ?",
            (status, utc_text(available_at), error_code, utc_text(now), task_id),
        )
