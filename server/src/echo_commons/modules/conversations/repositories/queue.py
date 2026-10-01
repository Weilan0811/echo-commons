import sqlite3
from datetime import datetime, timedelta

from echo_commons.execution.contracts import TaskLease
from echo_commons.infrastructure.database.mapping import utc_text


class ConversationQueueRepository:
    def claim(
        self, connection: sqlite3.Connection, owner: str, now: datetime, lease_seconds: float
    ) -> TaskLease | None:
        row = connection.execute(
            "SELECT t.* FROM conversation_tasks t JOIN communities c USING(community_id) "
            "JOIN conversations v USING(conversation_id) "
            "JOIN conversation_memberships m USING(membership_id) "
            "WHERE t.status IN ('pending','retry_wait') AND t.available_at_utc <= ? "
            "AND c.status = 'active' AND v.status = 'active' AND m.left_at_utc IS NULL "
            "ORDER BY t.available_at_utc, t.created_at_utc, t.task_id LIMIT 1",
            (utc_text(now),),
        ).fetchone()
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
            "conversation_reply",
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
