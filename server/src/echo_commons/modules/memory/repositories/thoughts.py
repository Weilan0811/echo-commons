import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text


class ThoughtRepository:
    def add(
        self,
        connection: sqlite3.Connection,
        result_id: str,
        community_id: str,
        character_id: str,
        conversation_id: str,
        game_day: str,
        content: str,
        now: datetime,
    ) -> str:
        thought_id = str(uuid4())
        connection.execute(
            "INSERT INTO thoughts (thought_id, result_id, community_id, character_id, "
            "conversation_id, game_day, content, content_version, created_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, '1', ?)",
            (
                thought_id,
                result_id,
                community_id,
                character_id,
                conversation_id,
                game_day,
                content,
                utc_text(now),
            ),
        )
        return thought_id
