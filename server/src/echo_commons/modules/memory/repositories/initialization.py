import sqlite3
from datetime import datetime

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.domain.authored import AuthorMaterial


class InitializationRepository:
    def pending(
        self, connection: sqlite3.Connection, phase: str | None = None
    ) -> tuple[sqlite3.Row, ...]:
        return tuple(
            connection.execute(
                "SELECT i.*,c.community_id,c.memory_mode FROM memory_initializations i "
                "JOIN character_instances c USING(character_id) "
                "JOIN communities m USING(community_id) "
                "WHERE c.memory_status='preparing' AND m.status='active' "
                "AND (? != 'organize' OR i.organization_run_id IS NULL OR EXISTS "
                "(SELECT 1 FROM reflection_graph_runs r WHERE r.graph_run_id=i.organization_run_id "
                "AND r.status IN ('completed','failed','partial','cancelled'))) "
                "AND (? IS NULL OR i.phase=?) ORDER BY i.created_at_utc,i.character_id LIMIT 16",
                (phase or "", phase, phase),
            )
        )

    def advance(
        self, connection: sqlite3.Connection, character_id: str, phase: str, now: datetime
    ) -> None:
        connection.execute(
            "UPDATE memory_initializations SET phase=?,error_code=NULL,updated_at_utc=? "
            "WHERE character_id=?",
            (phase, utc_text(now), character_id),
        )
        if phase == "completed":
            connection.execute(
                "UPDATE character_instances SET memory_status='ready',updated_at_utc=? "
                "WHERE character_id=?",
                (utc_text(now), character_id),
            )

    def fail(
        self, connection: sqlite3.Connection, character_id: str, code: str, now: datetime
    ) -> None:
        connection.execute(
            "UPDATE memory_initializations SET error_code=?,updated_at_utc=? WHERE character_id=?",
            (code, utc_text(now), character_id),
        )
        connection.execute(
            "UPDATE character_instances SET memory_status='failed',updated_at_utc=? "
            "WHERE character_id=?",
            (utc_text(now), character_id),
        )

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
            "UPDATE memory_initializations SET error_code=NULL, attempts=attempts+1, "
            "updated_at_utc=? "
            "WHERE character_id=?",
            (utc_text(now), character_id),
        )
        connection.execute(
            "UPDATE character_instances SET memory_status='preparing',updated_at_utc=? "
            "WHERE character_id=?",
            (utc_text(now), character_id),
        )
