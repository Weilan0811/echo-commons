from __future__ import annotations

import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.conversations.domain.conversation import Membership
from echo_commons.modules.social.domain import SocialTurn
from echo_commons.shared.errors import ConflictError, NotFoundError


class ConversationTaskRepository:
    def reserve(
        self, connection: sqlite3.Connection, turn: SocialTurn, member: Membership, now: datetime
    ) -> str:
        task_id, timestamp = str(uuid4()), utc_text(now)
        connection.execute(
            "INSERT INTO conversation_tasks (task_id,community_id,conversation_id,social_turn_id,"
            "character_id,membership_id,status,available_at_utc,created_at_utc,"
            "updated_at_utc,trace_id) "
            "VALUES (?,?,?,?,?,?,'pending',?,?,?,?)",
            (
                task_id,
                turn.community_id,
                turn.conversation_id,
                turn.social_turn_id,
                member.actor.actor_id,
                member.membership_id,
                timestamp,
                timestamp,
                timestamp,
                str(uuid4()),
            ),
        )
        return task_id

    def materialize(self, connection, task_id: str, snapshot: ContextSnapshot) -> None:
        connection.execute(
            "UPDATE conversation_tasks SET snapshot_id=?,snapshot_schema_version=?,snapshot_json=?,"
            "updated_at_utc=? WHERE task_id=? AND snapshot_id IS NULL AND attempt_count=0",
            (
                snapshot.snapshot_id,
                snapshot.schema_version,
                snapshot.model_dump_json(),
                utc_text(snapshot.prepared_at_utc),
                task_id,
            ),
        )

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
        if row["snapshot_json"] is None:
            raise ConflictError("Conversation task is waiting for context preparation")
        return ContextSnapshot.model_validate_json(row["snapshot_json"])

    def get(self, connection: sqlite3.Connection, task_id: str) -> sqlite3.Row:
        row = connection.execute(
            "SELECT t.*,s.initiation_id FROM conversation_tasks t "
            "JOIN social_turns s USING(social_turn_id) WHERE t.task_id = ?",
            (task_id,),
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

    def cancel_conversation(
        self, connection: sqlite3.Connection, conversation_id: str, now: datetime
    ) -> tuple[str, ...]:
        memberships = tuple(
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT membership_id FROM conversation_tasks WHERE conversation_id = ? "
                "AND status IN ('pending','processing','retry_wait','suspended')",
                (conversation_id,),
            )
        )
        turns = set()
        for membership_id in memberships:
            turns.update(self.cancel_membership(connection, membership_id, now))
        return tuple(sorted(turns))

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
