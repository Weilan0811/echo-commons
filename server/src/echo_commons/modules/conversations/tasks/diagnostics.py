from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.shared.errors import NotFoundError


class ConversationDiagnostics:
    def __init__(self, database: Database, tasks: ConversationTaskRepository) -> None:
        self.database, self.tasks = database, tasks

    def context(self, community_id: str, character_id: str, task_id: str) -> ContextSnapshot:
        with self.database.read() as connection:
            task = self.tasks.get(connection, task_id)
            if (task["community_id"], task["character_id"]) != (community_id, character_id):
                raise NotFoundError("Conversation task does not exist in this character scope")
            return self.tasks.snapshot(connection, task_id)
