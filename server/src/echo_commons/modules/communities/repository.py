from __future__ import annotations

import sqlite3

from echo_commons.infrastructure.database.mapping import utc_datetime
from echo_commons.modules.communities.domain import Community, CommunityStatus, Player
from echo_commons.shared.actors import ActorKind, ActorRef
from echo_commons.shared.errors import NotFoundError


class CommunityRepository:
    def get(self, connection: sqlite3.Connection, community_id: str) -> Community:
        row = connection.execute(
            "SELECT * FROM communities WHERE community_id = ?", (community_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("Community does not exist")
        return Community(
            row["community_id"],
            row["name"],
            row["timezone"],
            utc_datetime(row["world_time_utc"]),
            CommunityStatus(row["status"]),
            row["state_version"],
            utc_datetime(row["created_at_utc"]),
            utc_datetime(row["updated_at_utc"]),
        )

    def player(self, connection: sqlite3.Connection, player_id: str) -> Player:
        row = connection.execute(
            "SELECT * FROM players WHERE player_id = ?", (player_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("Player does not exist")
        return Player(row["player_id"], row["display_name"], utc_datetime(row["created_at_utc"]))

    def require_actor(
        self, connection: sqlite3.Connection, community_id: str, actor: ActorRef
    ) -> None:
        self.get(connection, community_id)
        if actor.kind is ActorKind.PLAYER:
            self.player(connection, actor.actor_id)
        elif (
            connection.execute(
                "SELECT 1 FROM character_instances WHERE community_id = ? AND character_id = ?",
                (community_id, actor.actor_id),
            ).fetchone()
            is None
        ):
            raise NotFoundError("Character does not belong to this community")

    def require_member(
        self, connection: sqlite3.Connection, community_id: str, actor: ActorRef
    ) -> None:
        self.require_actor(connection, community_id, actor)
        if (
            connection.execute(
                (
                    "SELECT 1 FROM community_members WHERE community_id = ? AND actor_kind = "
                    "? AND actor_id = ?"
                ),
                (community_id, actor.kind.value, actor.actor_id),
            ).fetchone()
            is None
        ):
            raise NotFoundError("Actor is not a community member")

    def members(self, connection: sqlite3.Connection, community_id: str) -> tuple[ActorRef, ...]:
        self.get(connection, community_id)
        return tuple(
            ActorRef(row["actor_kind"], row["actor_id"])
            for row in connection.execute(
                (
                    "SELECT actor_kind, actor_id FROM community_members WHERE community_id = "
                    "? ORDER BY actor_kind, actor_id"
                ),
                (community_id,),
            )
        )
