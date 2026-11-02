from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.social.contracts import (
    ParticipationResult,
    ResponseReservation,
    TaskDispatchResult,
)


class ActivitySources:
    def __init__(self, social_lifecycle):
        self.social = social_lifecycle

    def reserve(self, connection, turn, member, at):
        existing = connection.execute(
            "SELECT source_id AS task_id FROM activity_task_sources "
            "WHERE social_turn_id=? AND character_id=?",
            (turn.social_turn_id, member.actor.actor_id),
        ).fetchone()
        if existing:
            return existing["task_id"]
        identity = str(uuid4())
        connection.execute(
            "INSERT INTO activity_task_sources(source_id,social_turn_id,character_id,"
            "membership_id,observation_max_sequence,status,created_at_utc,updated_at_utc) "
            "VALUES (?,?,?,?,?,'reserved',?,?)",
            (
                identity,
                turn.social_turn_id,
                member.actor.actor_id,
                member.membership_id,
                turn.observation_max_sequence,
                utc_text(at),
                utc_text(at),
            ),
        )
        return identity

    def reservation(self, connection, turn_id):
        row = connection.execute(
            "SELECT source_id AS task_id,membership_id FROM activity_task_sources "
            "WHERE social_turn_id=? AND status IN ('reserved','queued')",
            (turn_id,),
        ).fetchone()
        return ResponseReservation(row["task_id"], row["membership_id"]) if row else None

    def create(self, connection, request, *, task_id=None):
        identity = task_id or self.reserve(connection, request.turn, request.member, request.at)
        connection.execute(
            "UPDATE activity_task_sources SET status='queued',observation_max_sequence=?,"
            "updated_at_utc=? WHERE source_id=? AND status='reserved'",
            (request.turn.observation_max_sequence, utc_text(request.at), identity),
        )
        return TaskDispatchResult(identity)

    def queued(self, connection, scope):
        return connection.execute(
            "SELECT a.* FROM activity_task_sources a JOIN social_turns s USING(social_turn_id) "
            "WHERE s.conversation_id=? AND a.membership_id=? AND a.status='queued' "
            "ORDER BY a.created_at_utc,a.source_id",
            (scope.conversation_id, scope.membership_id),
        ).fetchall()

    @staticmethod
    def message_ids(connection, source):
        return tuple(
            row[0]
            for row in connection.execute(
                "SELECT DISTINCT m.message_id,m.sequence FROM social_turn_batches b "
                "JOIN input_batch_messages bm USING(input_batch_id) "
                "JOIN messages m USING(message_id) "
                "WHERE b.social_turn_id=? AND m.sequence<=? ORDER BY m.sequence",
                (source["social_turn_id"], source["observation_max_sequence"]),
            )
        )

    def attach(self, connection, task_id, sources, now):
        for source in sources:
            connection.execute(
                "UPDATE activity_task_sources SET task_id=?,status='attached',updated_at_utc=? "
                "WHERE source_id=? AND status='queued'",
                (task_id, utc_text(now), source["source_id"]),
            )

    def finish(self, connection, task_id, outcome, now):
        for row in connection.execute(
            "SELECT * FROM activity_task_sources WHERE task_id=? "
            "AND status IN ('attached','frozen')",
            (task_id,),
        ).fetchall():
            self._finish(connection, row, outcome, now)

    def requeue(self, connection, task_id, now):
        connection.execute(
            "UPDATE activity_task_sources SET status='queued',task_id=NULL,updated_at_utc=? "
            "WHERE task_id=? AND status IN ('attached','frozen')",
            (utc_text(now), task_id),
        )

    def _finish(self, connection, row, outcome, now):
        connection.execute(
            "UPDATE activity_task_sources SET status=?,updated_at_utc=? WHERE source_id=?",
            (outcome, utc_text(now), row["source_id"]),
        )
        self.social.task_finished(
            connection,
            ParticipationResult(
                row["social_turn_id"],
                row["character_id"],
                outcome if outcome in ("failed", "cancelled") else "completed",
                outcome,
                membership_id=row["membership_id"],
                considered_through_sequence=row["observation_max_sequence"],
            ),
            now,
        )

    def cancel_turn(self, connection, turn_id, reason, at):
        # 合并的行动继续执行，只取消这次交流安排。
        connection.execute(
            "UPDATE activity_task_sources SET status='cancelled',updated_at_utc=? "
            "WHERE social_turn_id=? AND status IN ('reserved','queued','attached','frozen')",
            (utc_text(at), turn_id),
        )

    def reconcile(self, connection, now):
        rows = connection.execute(
            "SELECT a.* FROM activity_task_sources a "
            "JOIN social_turns s USING(social_turn_id) "
            "JOIN conversations c USING(conversation_id) "
            "JOIN conversation_memberships m ON m.membership_id=a.membership_id "
            "LEFT JOIN activity_tasks t ON t.task_id=a.task_id "
            "WHERE a.status IN ('reserved','queued','attached','frozen') AND "
            "(m.left_at_utc IS NOT NULL OR c.status!='active' OR s.status='cancelled' "
            "OR t.status IN ('failed','cancelled'))"
        ).fetchall()
        for row in rows:
            task = connection.execute(
                "SELECT status FROM activity_tasks WHERE task_id=?", (row["task_id"],)
            ).fetchone()
            self._finish(
                connection, row, "failed" if task and task[0] == "failed" else "cancelled", now
            )
