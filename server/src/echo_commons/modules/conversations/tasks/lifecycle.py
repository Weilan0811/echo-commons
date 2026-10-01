import sqlite3
from datetime import datetime

from echo_commons.modules.communities.domain import CommunityStatus
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.modules.social.completion import TurnCompletion


class TaskLifecycle:
    def __init__(self, tasks: ConversationTaskRepository, completion: TurnCompletion) -> None:
        self.tasks, self.completion = tasks, completion

    def community_changed(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        status: CommunityStatus,
        now: datetime,
    ) -> None:
        if status is CommunityStatus.PAUSED:
            self.tasks.suspend_community(connection, community_id, now)
        else:
            for turn in self.tasks.resume_community(connection, community_id, now):
                self.completion.update(connection, turn, now)

    def member_left(
        self, connection: sqlite3.Connection, membership_id: str, now: datetime
    ) -> None:
        for turn in self.tasks.cancel_membership(connection, membership_id, now):
            self.completion.update(connection, turn, now)

    def archived(self, connection: sqlite3.Connection, conversation_id: str, now: datetime) -> None:
        for turn in self.tasks.cancel_conversation(connection, conversation_id, now):
            self.completion.update(connection, turn, now)
