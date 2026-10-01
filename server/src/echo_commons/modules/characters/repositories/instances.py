from __future__ import annotations

import sqlite3

from echo_commons.infrastructure.database.mapping import utc_datetime
from echo_commons.modules.characters.domain.instance import AvailabilityStatus, CharacterInstance
from echo_commons.shared.errors import NotFoundError


class InstanceRepository:
    def get(
        self, connection: sqlite3.Connection, community_id: str, character_id: str
    ) -> CharacterInstance:
        row = connection.execute(
            "SELECT * FROM character_instances WHERE community_id = ? AND character_id = ?",
            (community_id, character_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Character instance does not exist in this community")
        return CharacterInstance(
            row["character_id"],
            row["community_id"],
            row["blueprint_id"],
            row["blueprint_version"],
            AvailabilityStatus(row["availability_status"]),
            row["availability_reason"],
            utc_datetime(row["next_check_at_utc"]) if row["next_check_at_utc"] else None,
            row["availability_version"],
            utc_datetime(row["created_at_utc"]),
            utc_datetime(row["updated_at_utc"]),
        )

    def list(
        self, connection: sqlite3.Connection, community_id: str
    ) -> tuple[CharacterInstance, ...]:
        return tuple(
            self.get(connection, community_id, row[0])
            for row in connection.execute(
                "SELECT character_id FROM character_instances WHERE community_id = ? "
                "ORDER BY created_at_utc, character_id",
                (community_id,),
            )
        )
