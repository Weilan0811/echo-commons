from echo_commons.execution.contracts import TaskLease
from echo_commons.execution.observations import ExecutionEventPayload
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


class ActivityLifecycle:
    def __init__(
        self,
        database,
        observations,
        conversations,
        review,
        tasks,
        recorder,
        conversation_lifecycle,
        events,
        sources,
    ):
        self.database, self.observations, self.conversations = database, observations, conversations
        self.review, self.tasks, self.recorder = review, tasks, recorder
        self.conversation_lifecycle, self.events = conversation_lifecycle, events
        self.sources = sources
        self.expressions = None
        self.reactions = None

    def attach(self):
        self.conversation_lifecycle.activity = self
        self.events.activity_lifecycle = self

    def changed(self, connection, now, *, game_id=None, include_processing=True):
        self.reconcile_in(connection, now, game_id=game_id, include_processing=include_processing)

    def reconcile_in(self, connection, now, *, game_id=None, include_processing=True):
        where, params = (" WHERE game_id=?", (game_id,)) if game_id else ("", ())
        for row in connection.execute(
            "SELECT * FROM activity_working_memory" + where, params
        ).fetchall():
            active = False
            try:
                context = self.observations.participation.participant_context(
                    connection,
                    row["community_id"],
                    ActorRef("character", row["character_id"]),
                    row["game_id"],
                    row["participation_id"],
                )
                active = (
                    context.game.status == "running"
                    and self.conversations.get(
                        connection, row["community_id"], context.conversation_id
                    ).status
                    == "active"
                )
            except NotFoundError:
                pass
            if not active:
                connection.execute(
                    "DELETE FROM activity_working_memory WHERE community_id=? "
                    "AND character_id=? AND game_id=? AND participation_id=?",
                    (
                        row["community_id"],
                        row["character_id"],
                        row["game_id"],
                        row["participation_id"],
                    ),
                )
        task_where = " WHERE status IN ('pending','processing','retry_wait','suspended')"
        if game_id:
            task_where += " AND game_id=?"
        for row in connection.execute(
            "SELECT * FROM activity_tasks" + task_where, params
        ).fetchall():
            if not include_processing and row["status"] == "processing":
                continue
            code = self.review.source_code(connection, row)
            if code in ("community_paused", "character_unavailable"):
                state = "suspended"
            elif code:
                state = "cancelled"
            elif row["status"] == "suspended":
                state = "pending"
            else:
                continue
            if state == row["status"]:
                continue
            if code == "opportunity_replaced" and self.review.can_requeue_reply(connection, row):
                self.sources.requeue(connection, row["task_id"], now)
            connection.execute(
                "UPDATE activity_tasks SET status=?,lease_owner=NULL,lease_until_utc=NULL,"
                "lease_generation=lease_generation+1,last_error_code=?,updated_at_utc=? "
                "WHERE task_id=?",
                (state, code, utc_text(now), row["task_id"]),
            )
            lease = TaskLease(
                row["task_id"],
                f"activity_{row['purpose']}",
                row["attempt_count"],
                row["lease_generation"] + 1,
                row["lease_owner"] or "lifecycle",
                now,
                row["trace_id"],
            )
            self.recorder.record(
                connection,
                lease,
                "lifecycle_changed",
                ExecutionEventPayload(reason_code=code or "activity_resumed", task_state=state),
                now,
            )
        self.sources.reconcile(connection, now)
        if self.expressions:
            self.expressions.reconcile_in(connection, now)
        if self.reactions:
            self.reactions.reconcile_in(connection, now)
