import sqlite3
from datetime import datetime

from echo_commons.execution.records import ExecutionRecorder
from echo_commons.modules.communities.domain import CommunityStatus
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.social.completion import TurnCompletion


class TaskLifecycle:
    def __init__(
        self,
        tasks: ConversationTaskRepository,
        completion: TurnCompletion,
        recorder: ExecutionRecorder,
    ) -> None:
        self.tasks, self.completion = tasks, completion
        self.recorder = recorder

    def community_changed(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        status: CommunityStatus,
        now: datetime,
    ) -> None:
        rows = connection.execute(
            (
                "SELECT * FROM conversation_tasks WHERE community_id=? "
                "AND status IN ('pending','processing','retry_wait','suspended')"
            ),
            (community_id,),
        ).fetchall()
        if status is CommunityStatus.PAUSED:
            self.tasks.suspend_community(connection, community_id, now)
        else:
            for turn in self.tasks.resume_community(connection, community_id, now):
                self.completion.update(connection, turn, now)
        self.recorder.lifecycle(
            connection,
            rows,
            "community_paused" if status is CommunityStatus.PAUSED else "community_resumed",
            now,
        )

    def member_left(
        self, connection: sqlite3.Connection, membership_id: str, now: datetime
    ) -> None:
        rows = connection.execute(
            (
                "SELECT * FROM conversation_tasks WHERE membership_id=? "
                "AND status IN ('pending','processing','retry_wait','suspended')"
            ),
            (membership_id,),
        ).fetchall()
        for turn in self.tasks.cancel_membership(connection, membership_id, now):
            self.completion.update(connection, turn, now)
        self.recorder.lifecycle(connection, rows, "member_left", now)

    def archived(self, connection: sqlite3.Connection, conversation_id: str, now: datetime) -> None:
        rows = connection.execute(
            (
                "SELECT * FROM conversation_tasks WHERE conversation_id=? "
                "AND status IN ('pending','processing','retry_wait','suspended')"
            ),
            (conversation_id,),
        ).fetchall()
        for turn in self.tasks.cancel_conversation(connection, conversation_id, now):
            self.completion.update(connection, turn, now)
        for row in rows:
            connection.execute(
                "UPDATE conversation_tasks SET last_error_code='conversation_archived' "
                "WHERE task_id=?",
                (row["task_id"],),
            )
        self.recorder.lifecycle(connection, rows, "conversation_archived", now)
