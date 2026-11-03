import sqlite3

from echo_commons.agents.contracts.activity import ActivityPreparation, ActivityScope
from echo_commons.shared.errors import IdempotencyConflict, NotFoundError


def scope_values(scope: ActivityScope) -> tuple[str, str, str, str]:
    return scope.community_id, scope.character_id, scope.game_id, scope.participation_id


class ActivityInputRepository:
    def find(self, connection, community_id, character_id, input_id):
        return connection.execute(
            "SELECT * FROM activity_inputs WHERE community_id=? AND character_id=? AND input_id=?",
            (community_id, character_id, input_id),
        ).fetchone()

    def get(self, connection, community_id, character_id, input_id):
        row = self.find(connection, community_id, character_id, input_id)
        if row is None:
            raise NotFoundError("Activity input is outside this character scope")
        return row

    def add(self, connection: sqlite3.Connection, preparation: ActivityPreparation, request: str):
        scope = preparation.scope
        connection.execute(
            "INSERT INTO activity_inputs(input_id,community_id,character_id,game_id,"
            "participation_id,kind,request_json,preparation_json,created_at_utc) "
            "VALUES (?,?,?,?,?,?,?,?,?)",
            (
                preparation.input_id,
                *scope_values(scope),
                preparation.kind,
                request,
                preparation.model_dump_json(),
                preparation.evidence.conversation.prepared_at_utc.isoformat(),
            ),
        )

    def save_stage(self, connection, community_id, character_id, input_id, stage, content):
        if stage not in ("memory_json", "projection_json", "analysis_json", "snapshot_json"):
            raise ValueError("Unknown activity input stage")
        row = self.get(connection, community_id, character_id, input_id)
        if (
            row[stage] is not None
            and row[stage] != content
            and not (stage == "memory_json" and row["snapshot_json"] is None)
        ):
            raise IdempotencyConflict("Activity input stage already has a different result")
        mutable = "snapshot_json" if stage == "memory_json" else stage
        connection.execute(
            f"UPDATE activity_inputs SET {stage}=? WHERE input_id=? AND {mutable} IS NULL",
            (content, input_id),
        )

    def progress(self, connection, scope):
        row = connection.execute(
            "SELECT event_sequence,message_sequence,version FROM activity_observation_progress "
            "WHERE community_id=? AND character_id=? AND game_id=? AND participation_id=?",
            scope_values(scope),
        ).fetchone()
        return tuple(row) if row else (0, 0, 0)
