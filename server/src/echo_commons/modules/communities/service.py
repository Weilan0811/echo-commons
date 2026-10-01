from __future__ import annotations

from datetime import UTC, datetime
from uuid import uuid4
from zoneinfo import ZoneInfo

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.communities.contracts import CommunityLifecycle
from echo_commons.modules.communities.domain import Community, CommunityStatus, Player
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError


class CommunityService:
    def __init__(
        self, database: Database, repository: CommunityRepository, lifecycle: CommunityLifecycle
    ) -> None:
        self.database = database
        self.repository = repository
        self.lifecycle = lifecycle

    def create(
        self,
        name: str,
        timezone: str,
        *,
        community_id: str | None = None,
        world_time: datetime | None = None,
    ) -> Community:
        community_id = str(uuid4()) if community_id is None else community_id
        ZoneInfo(timezone)
        now = datetime.now(UTC)
        candidate = Community(
            community_id,
            name.strip(),
            timezone,
            world_time or now,
            CommunityStatus.ACTIVE,
            0,
            now,
            now,
        )
        with self.database.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM communities WHERE community_id = ?", (community_id,)
            ).fetchone():
                existing = self.repository.get(connection, community_id)
                if (existing.name, existing.timezone) != (candidate.name, candidate.timezone):
                    raise ConflictError("Community ID already has different content")
                return existing
            connection.execute(
                "INSERT INTO communities VALUES (?, ?, ?, ?, ?, ?, ?, ?)",
                (
                    community_id,
                    candidate.name,
                    timezone,
                    utc_text(candidate.world_time_utc),
                    "active",
                    0,
                    utc_text(now),
                    utc_text(now),
                ),
            )
            return candidate

    def register_player(self, display_name: str, *, player_id: str | None = None) -> Player:
        candidate = Player(
            str(uuid4()) if player_id is None else player_id,
            display_name.strip(),
            datetime.now(UTC),
        )
        with self.database.transaction() as connection:
            if connection.execute(
                "SELECT 1 FROM players WHERE player_id = ?", (candidate.player_id,)
            ).fetchone():
                existing = self.repository.player(connection, candidate.player_id)
                if existing.display_name != candidate.display_name:
                    raise ConflictError("Player ID already has a different display name")
                return existing
            connection.execute(
                "INSERT INTO players VALUES (?, ?, ?)",
                (candidate.player_id, candidate.display_name, utc_text(candidate.created_at_utc)),
            )
            return candidate

    def join(self, community_id: str, actor: ActorRef) -> None:
        with self.database.transaction() as connection:
            self.repository.require_actor(connection, community_id, actor)
            connection.execute(
                "INSERT INTO community_members VALUES (?, ?, ?, ?) ON CONFLICT DO NOTHING",
                (community_id, actor.kind.value, actor.actor_id, utc_text(datetime.now(UTC))),
            )

    def update(
        self,
        community_id: str,
        *,
        expected_version: int,
        status: CommunityStatus | None = None,
        world_time: datetime | None = None,
    ) -> Community:
        with self.database.transaction() as connection:
            current = self.repository.get(connection, community_id)
            if expected_version != current.state_version:
                raise ConflictError("Community state version has changed")
            new_status = CommunityStatus(status) if status is not None else current.status
            new_time = world_time if world_time is not None else current.world_time_utc
            if new_time < current.world_time_utc:
                raise ValueError("Community world time cannot move backwards")
            if (new_status, new_time) == (current.status, current.world_time_utc):
                return current
            now = datetime.now(UTC)
            connection.execute(
                "UPDATE communities SET status = ?, world_time_utc = ?, state_version = "
                "state_version + 1, updated_at_utc = ? WHERE community_id = ?",
                (new_status.value, utc_text(new_time), utc_text(now), community_id),
            )
            if new_status != current.status:
                self.lifecycle.community_changed(connection, community_id, new_status, now)
            return self.repository.get(connection, community_id)
