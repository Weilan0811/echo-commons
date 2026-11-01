import sqlite3
from datetime import datetime

from echo_commons.execution.records import ExecutionRecorder
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.conversations.domain.conversation import Membership
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.tasks.context import ConversationContext
from echo_commons.modules.conversations.tasks.memory import ContextBudgetExceeded
from echo_commons.modules.social.contracts import (
    ParticipationPreparation,
    ResponseRequest,
    ResponseReservation,
    TaskDispatchResult,
)
from echo_commons.modules.social.domain import SocialTurn
from echo_commons.shared.errors import ConflictError


class TaskCancellation:
    def __init__(self, recorder: ExecutionRecorder) -> None:
        self.recorder = recorder

    def cancel_turn(
        self, connection: sqlite3.Connection, turn_id: str, reason: str, at: datetime
    ) -> None:
        rows = connection.execute(
            "SELECT * FROM conversation_tasks WHERE social_turn_id=? "
            "AND status IN ('pending','processing','retry_wait','suspended')",
            (turn_id,),
        ).fetchall()
        connection.execute(
            "UPDATE conversation_tasks SET status='cancelled', lease_owner=NULL, "
            "lease_until_utc=NULL, lease_generation=lease_generation+1, last_error_code=?, "
            "updated_at_utc=? WHERE social_turn_id=? "
            "AND status IN ('pending','processing','retry_wait','suspended')",
            (reason, utc_text(at), turn_id),
        )
        self.recorder.lifecycle(connection, rows, reason, at)


class ConversationTaskDispatcher(TaskCancellation):
    def reservation(self, connection, turn_id):
        row = connection.execute(
            "SELECT task_id,membership_id FROM conversation_tasks WHERE social_turn_id=? "
            "AND status IN ('pending','suspended')",
            (turn_id,),
        ).fetchone()
        return ResponseReservation(row["task_id"], row["membership_id"]) if row else None

    def __init__(
        self,
        tasks: ConversationTaskRepository,
        context: ConversationContext,
        recorder: ExecutionRecorder,
        participation: ParticipationPreparation | None = None,
    ) -> None:
        super().__init__(recorder)
        self.tasks, self.context = tasks, context
        self.participation = participation

    def reserve(self, connection, turn: SocialTurn, member: Membership, at: datetime) -> str:
        task_id = self.tasks.reserve(connection, turn, member, at)
        if self.context.communities.get(connection, turn.community_id).status == "paused":
            connection.execute(
                "UPDATE conversation_tasks SET status='suspended' WHERE task_id=?", (task_id,)
            )
        return task_id

    def create(
        self,
        connection: sqlite3.Connection,
        request: ResponseRequest,
        *,
        task_id: str | None = None,
    ) -> TaskDispatchResult:
        conversation = self.context.conversations.get(
            connection, request.turn.community_id, request.turn.conversation_id
        )
        if conversation.kind == "game" and request.turn.initiation_id is None:
            raise ConflictError("Game conversations use activity decisions")
        situation = ""
        if request.turn.initiation_id:
            situation = connection.execute(
                "SELECT situation FROM conversation_initiations WHERE initiation_id=?",
                (request.turn.initiation_id,),
            ).fetchone()[0]
        try:
            snapshot = self.context.prepare(
                connection,
                request.turn,
                request.member,
                request.inputs,
                request.at,
                situation=situation,
            )
        except ContextBudgetExceeded as error:
            if task_id is None:
                task_id = self.tasks.prepare(connection, error.snapshot)
            else:
                self.tasks.materialize(connection, task_id, error.snapshot)
            rows = [self.tasks.get(connection, task_id)]
            connection.execute(
                "UPDATE conversation_tasks SET status='failed',last_error_code=? WHERE task_id=?",
                ("context_budget_exceeded", task_id),
            )
            self.recorder.lifecycle(connection, rows, "context_budget_exceeded", request.at)
            return TaskDispatchResult(task_id, "context_budget_exceeded")
        if task_id is None:
            task_id = self.tasks.prepare(connection, snapshot)
        else:
            self.tasks.materialize(connection, task_id, snapshot)
        if self.participation is not None:
            self.participation.freeze(connection, task_id, snapshot)
        if self.context.communities.get(connection, request.turn.community_id).status == "paused":
            connection.execute(
                "UPDATE conversation_tasks SET status='suspended' WHERE task_id=?", (task_id,)
            )
        return TaskDispatchResult(task_id)
