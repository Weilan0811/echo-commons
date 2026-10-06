import sqlite3
from datetime import datetime

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.domain.authored import AuthorMaterial


class InitializationRepository:
    def register(
        self,
        connection: sqlite3.Connection,
        character_id: str,
        blueprint_id: str,
        blueprint_version: str,
        materials: tuple[AuthorMaterial, ...],
        now: datetime,
    ) -> None:
        for material in materials:
            connection.execute(
                "INSERT INTO memory_author_materials VALUES (?,?,?,?,?,?,?,?,?,?) "
                "ON CONFLICT(character_id,material_kind,position) DO NOTHING",
                (
                    f"{character_id}:{material.kind}:{material.position}",
                    character_id,
                    blueprint_id,
                    blueprint_version,
                    material.kind,
                    material.position,
                    material.content,
                    material.question_id,
                    material.question,
                    utc_text(now),
                ),
            )
        connection.execute(
            "INSERT INTO memory_initializations "
            "(character_id,phase,created_at_utc,updated_at_utc) VALUES (?,'materials',?,?)",
            (character_id, utc_text(now), utc_text(now)),
        )

    def retry(self, connection: sqlite3.Connection, character_id: str, now: datetime) -> None:
        connection.execute(
            "UPDATE memory_initializations SET error_code=NULL, updated_at_utc=? "
            "WHERE character_id=?",
            (utc_text(now), character_id),
        )
        connection.execute(
            "UPDATE character_instances SET memory_status='preparing',updated_at_utc=? "
            "WHERE character_id=?",
            (utc_text(now), character_id),
        )
