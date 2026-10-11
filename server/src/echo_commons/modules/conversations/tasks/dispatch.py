import sqlite3
from datetime import datetime

from echo_commons.execution.records import ExecutionRecorder
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.conversations.tasks.context import ConversationContext
from echo_commons.modules.conversations.tasks.memory import ContextBudgetExceeded
from echo_commons.modules.social.contracts import ResponseRequest, TaskDispatchResult


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
    def __init__(
        self,
        tasks: ConversationTaskRepository,
        context: ConversationContext,
        recorder: ExecutionRecorder,
    ) -> None:
        super().__init__(recorder)
        self.tasks, self.context = tasks, context

    def create(
        self, connection: sqlite3.Connection, request: ResponseRequest
    ) -> TaskDispatchResult:
        try:
            snapshot = self.context.prepare(
                connection,
                request.turn,
                request.member,
                request.inputs,
                request.at,
                root_inputs=request.root_inputs,
            )
        except ContextBudgetExceeded as error:
            task_id = self.tasks.prepare(connection, error.snapshot)
            rows = [self.tasks.get(connection, task_id)]
            connection.execute(
                "UPDATE conversation_tasks SET status='failed',last_error_code=? WHERE task_id=?",
                ("context_budget_exceeded", task_id),
            )
            self.recorder.lifecycle(connection, rows, "context_budget_exceeded", request.at)
            return TaskDispatchResult(task_id, "context_budget_exceeded")
        return TaskDispatchResult(self.tasks.prepare(connection, snapshot))
