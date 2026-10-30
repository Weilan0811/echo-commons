import sqlite3
from datetime import datetime
from uuid import uuid4

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.shared.errors import NotFoundError


class ThoughtRepository:
    def add_activity(
        self,
        connection,
        result_id,
        community_id,
        character_id,
        conversation_id,
        game_day,
        content,
        now,
    ):
        thought_id = str(uuid4())
        connection.execute(
            "INSERT INTO thoughts(thought_id,activity_result_id,community_id,character_id,"
            "conversation_id,game_day,content,content_version,created_at_utc) "
            "VALUES (?,?,?,?,?,?,?,'1',?)",
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

    def for_results(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        result_ids: tuple[str, ...],
        recorded_before: datetime,
    ) -> dict[str, sqlite3.Row]:
        if not result_ids:
            return {}
        placeholders = ",".join("?" for _ in result_ids)
        rows = connection.execute(
            "SELECT t.* FROM thoughts t JOIN conversation_results r ON r.result_id = t.result_id "
            "WHERE t.community_id = ? AND t.character_id = ? "
            "AND t.content IS NOT NULL AND t.created_at_utc <= ? AND r.status = 'approved' "
            f"AND t.result_id IN ({placeholders})",
            (community_id, character_id, utc_text(recorded_before), *result_ids),
        )
        return {row["result_id"]: row for row in rows}

    def get(
        self, connection: sqlite3.Connection, community_id: str, character_id: str, thought_id: str
    ) -> sqlite3.Row:
        row = connection.execute(
            "SELECT * FROM thoughts WHERE community_id = ? AND character_id = ? AND thought_id = ?",
            (community_id, character_id, thought_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Thought does not exist in the character scope")
        return row

    def clear_text(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        thought_id: str,
        now: datetime,
    ) -> bool:
        self.get(connection, community_id, character_id, thought_id)
        updated = (
            connection.execute(
                "UPDATE thoughts SET content = NULL, content_removed_at_utc = ? "
                "WHERE community_id = ? AND character_id = ? AND thought_id = ? "
                "AND content IS NOT NULL",
                (utc_text(now), community_id, character_id, thought_id),
            ).rowcount
            == 1
        )
        if updated:
            connection.execute(
                "UPDATE memory_cognitions SET status='needs_review' WHERE status='current' "
                "AND (memory_id,version) IN (SELECT memory_id,version FROM "
                "memory_cognition_sources "
                "WHERE source_kind='thought' AND source_id=?)",
                (thought_id,),
            )
        return updated

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
