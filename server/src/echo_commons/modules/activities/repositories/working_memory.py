from echo_commons.agents.contracts.activity import WorkingMemory
from echo_commons.modules.activities.repositories.inputs import scope_values


class WorkingMemoryRepository:
    def read(self, connection, scope) -> WorkingMemory:
        row = connection.execute(
            "SELECT content_json FROM activity_working_memory WHERE community_id=? "
            "AND character_id=? AND game_id=? AND participation_id=?",
            scope_values(scope),
        ).fetchone()
        return WorkingMemory.model_validate_json(row[0]) if row else WorkingMemory()

    def save(self, connection, scope, value: WorkingMemory):
        connection.execute(
            "INSERT INTO activity_working_memory VALUES (?,?,?,?,?,?,?) "
            "ON CONFLICT(community_id,character_id,game_id,participation_id) DO UPDATE SET "
            "version=excluded.version,content_json=excluded.content_json,last_input_id=excluded.last_input_id",
            (*scope_values(scope), value.version, value.model_dump_json(), value.last_input_id),
        )

    def clear(self, connection, scope):
        connection.execute(
            "DELETE FROM activity_working_memory WHERE community_id=? AND character_id=? "
            "AND game_id=? AND participation_id=?",
            scope_values(scope),
        )
