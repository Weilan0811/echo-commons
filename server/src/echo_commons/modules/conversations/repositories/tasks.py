from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.shared.errors import ConflictError, NotFoundError


class ConversationTaskRepository:
    def prepare(self, connection: sqlite3.Connection, snapshot: ContextSnapshot) -> str:
        scope, now = snapshot.scope, utc_text(snapshot.prepared_at_utc)
        member = connection.execute(
            "SELECT 1 FROM conversation_memberships WHERE community_id = ? AND "
            "conversation_id = ? AND membership_id = ? AND actor_kind = 'character' "
            "AND actor_id = ? AND left_at_utc IS NULL",
            (scope.community_id, scope.conversation_id, scope.membership_id, scope.character_id),
        ).fetchone()
        if member is None:
            raise ConflictError("Task snapshot does not belong to the active character membership")
        task_id = str(uuid4())
        connection.execute(
            "INSERT INTO conversation_tasks (task_id, community_id, conversation_id, "
            "social_turn_id, character_id, membership_id, snapshot_id, snapshot_schema_version, "
            "snapshot_json, status, available_at_utc, created_at_utc, updated_at_utc, trace_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                task_id,
                scope.community_id,
                scope.conversation_id,
                scope.social_turn_id,
                scope.character_id,
                scope.membership_id,
                snapshot.snapshot_id,
                snapshot.schema_version,
                snapshot.model_dump_json(),
                "pending",
                now,
                now,
                now,
                str(uuid4()),
            ),
        )
        return task_id

    def snapshot(self, connection: sqlite3.Connection, task_id: str) -> ContextSnapshot:
        row = self.get(connection, task_id)
        return ContextSnapshot.model_validate_json(row["snapshot_json"])

    def get(self, connection: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM conversation_tasks WHERE task_id = ?", (task_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("Conversation task does not exist")
        return row

    def cancel_membership(
        self, connection: sqlite3.Connection, membership_id: str, now: datetime
    ) -> tuple[str, ...]:
        rows = connection.execute(
            "SELECT social_turn_id, character_id FROM conversation_tasks WHERE membership_id = ? "
            "AND status IN ('pending','processing','retry_wait','suspended')",
            (membership_id,),
        ).fetchall()
        connection.execute(
            "UPDATE conversation_tasks SET status = 'cancelled', lease_owner = NULL, "
            "lease_until_utc = NULL, lease_generation = lease_generation + 1, "
            "last_error_code = 'member_left', updated_at_utc = ? WHERE membership_id = ? "
            "AND status IN ('pending','processing','retry_wait','suspended')",
            (utc_text(now), membership_id),
        )
        for row in rows:
            connection.execute(
                "UPDATE participation_decisions SET status = 'cancelled', outcome = 'cancelled', "
                "updated_at_utc = ? WHERE social_turn_id = ? AND character_id = ? "
                "AND status = 'selected'",
                (utc_text(now), row["social_turn_id"], row["character_id"]),
            )
        return tuple(sorted({row["social_turn_id"] for row in rows}))

    def suspend_community(
        self, connection: sqlite3.Connection, community_id: str, now: datetime
    ) -> int:
        return connection.execute(
            "UPDATE conversation_tasks SET status = 'suspended', lease_owner = NULL, "
            "lease_until_utc = NULL, lease_generation = lease_generation + 1, "
            "updated_at_utc = ? WHERE community_id = ? "
            "AND status IN ('pending','processing','retry_wait')",
            (utc_text(now), community_id),
        ).rowcount

    def resume_community(
        self, connection: sqlite3.Connection, community_id: str, now: datetime
    ) -> tuple[str, ...]:
        rows = connection.execute(
            "SELECT * FROM conversation_tasks WHERE community_id = ? AND status = 'suspended'",
            (community_id,),
        ).fetchall()
        for row in rows:
            member = connection.execute(
                "SELECT left_at_utc FROM conversation_memberships WHERE membership_id = ?",
                (row["membership_id"],),
            ).fetchone()
            if member["left_at_utc"] is not None:
                self.cancel_membership(connection, row["membership_id"], now)
            else:
                connection.execute(
                    "UPDATE conversation_tasks SET status = 'pending', available_at_utc = ?, "
                    "updated_at_utc = ? WHERE task_id = ? AND status = 'suspended'",
                    (utc_text(now), utc_text(now), row["task_id"]),
                )
        return tuple(sorted({row["social_turn_id"] for row in rows}))
