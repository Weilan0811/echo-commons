from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.conversations.repositories.tasks import ConversationTaskRepository
from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.inspection import redact_thoughts


class ConversationDiagnostics:
    def __init__(self, database: Database, tasks: ConversationTaskRepository) -> None:
        self.database, self.tasks = database, tasks

    def context(self, community_id: str, character_id: str, task_id: str) -> dict:
        with self.database.read() as connection:
            task = self.tasks.get(connection, task_id)
            if (task["community_id"], task["character_id"]) != (community_id, character_id):
                raise NotFoundError("Conversation task does not exist in this character scope")
            return redact_thoughts(
                connection,
                community_id,
                character_id,
                self.tasks.snapshot(connection, task_id).model_dump(mode="json"),
            )
