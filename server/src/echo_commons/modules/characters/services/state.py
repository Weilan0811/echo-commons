from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.characters.domain.instance import AvailabilityStatus, CharacterInstance
from echo_commons.modules.characters.domain.state import StateEntry, StateKind
from echo_commons.modules.characters.repositories.instances import InstanceRepository
from echo_commons.modules.characters.repositories.state import StateRepository
from echo_commons.shared.errors import ConflictError


class CharacterStateService:
    def __init__(
        self, database: Database, instances: InstanceRepository, states: StateRepository
    ) -> None:
        self.database, self.instances, self.states = database, instances, states

    def record(
        self,
        community_id: str,
        character_id: str,
        kind: StateKind,
        value: str,
        source_kind: str,
        source_ref: str,
        *,
        expected_version: int,
        expires_at: datetime | None = None,
    ) -> StateEntry:
        now = datetime.now(UTC)
        with self.database.transaction() as connection:
            self.instances.get(connection, community_id, character_id)
            existing = connection.execute(
                "SELECT * FROM character_state_entries WHERE character_id = ? AND "
                "state_kind = ? AND source_kind = ? AND source_ref = ?",
                (character_id, kind.value, source_kind, source_ref),
            ).fetchone()
            if existing:
                entry = self.states.from_row(existing)
                if (entry.value, entry.expires_at_utc) != (value, expires_at):
                    raise ConflictError("State source already records different content")
                return entry
            version = connection.execute(
                "SELECT COALESCE(MAX(state_version), 0) FROM character_state_entries "
                "WHERE character_id = ? AND state_kind = ?",
                (character_id, kind.value),
            ).fetchone()[0]
            if expected_version != version:
                raise ConflictError("State version has changed")
            entry = StateEntry(
                str(uuid4()),
                community_id,
                character_id,
                kind,
                value,
                source_kind,
                source_ref,
                version + 1,
                now,
                expires_at,
            )
            self.states.add(connection, entry)
            return entry

    def set_availability(
        self,
        community_id: str,
        character_id: str,
        status: AvailabilityStatus,
        *,
        expected_version: int,
        reason: str | None = None,
        next_check_at: datetime | None = None,
    ) -> CharacterInstance:
        status = AvailabilityStatus(status)
        with self.database.transaction() as connection:
            current = self.instances.get(connection, community_id, character_id)
            if expected_version != current.availability_version:
                raise ConflictError("Availability version has changed")
            if (status, reason, next_check_at) == (
                current.availability_status,
                current.availability_reason,
                current.next_check_at_utc,
            ):
                return current
            connection.execute(
                "UPDATE character_instances SET availability_status = ?, "
                "availability_reason = ?, next_check_at_utc = ?, availability_version = "
                "availability_version + 1, updated_at_utc = ? WHERE community_id = ? AND "
                "character_id = ?",
                (
                    status.value,
                    reason,
                    utc_text(next_check_at) if next_check_at else None,
                    utc_text(datetime.now(UTC)),
                    community_id,
                    character_id,
                ),
            )
            return self.instances.get(connection, community_id, character_id)
