from dataclasses import asdict

from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.management import read_page


class CommunityQuery:
    def __init__(self, database, identity):
        self.database, self.identity = database, identity
        self.repository = CommunityRepository()

    def players(self, options):
        with self.database.read() as connection:
            return read_page(
                connection,
                "SELECT * FROM players",
                (),
                scope={"query": "public_players"},
                order=("created_at_utc", "player_id"),
                options=options,
            )

    def player(self, player_id):
        with self.database.read() as connection:
            return self.repository.player(connection, player_id)

    def communities(self, player_id, scope, options):
        with self.database.read() as connection:
            self.repository.player(connection, player_id)
            return read_page(
                connection,
                "SELECT c.community_id,c.name,c.timezone,c.status,c.cover_kind,c.cover_ref, "
                "EXISTS (SELECT 1 FROM community_members cm WHERE cm.community_id=c.community_id "
                "AND cm.actor_kind='player' AND cm.actor_id=?) AS joined FROM communities c "
                "WHERE EXISTS (SELECT 1 FROM community_members cm "
                "WHERE cm.community_id=c.community_id "
                "AND cm.actor_kind='player' AND cm.actor_id=?)=?",
                (player_id, player_id, int(scope == "joined")),
                scope={"query": "public_communities", "player_id": player_id, "scope": scope},
                order=("community_id",),
                options=options,
            )

    def community(self, community_id, player_id):
        with self.database.read() as connection:
            self.repository.require_member(connection, community_id, ActorRef("player", player_id))
            return self.repository.get(connection, community_id)

    def members(self, community_id, player_id, options):
        with self.database.read() as connection:
            self.repository.require_member(connection, community_id, ActorRef("player", player_id))
            page = read_page(
                connection,
                "SELECT * FROM community_members WHERE community_id=?",
                (community_id,),
                scope={
                    "query": "public_community_members",
                    "community_id": community_id,
                    "player_id": player_id,
                },
                order=("actor_kind", "actor_id"),
                options=options,
            )
            page["items"] = [
                self.identity.display(
                    connection, community_id, ActorRef(row["actor_kind"], row["actor_id"])
                )
                for row in page["items"]
            ]
            return page

    def character_view(self, instance):
        with self.database.read() as connection:
            data = asdict(instance)
            display = self.identity.display(
                connection, instance.community_id, ActorRef("character", instance.character_id)
            )
            data.update(
                display_name=display.display_name,
                avatar_url=display.avatar_url,
                illustration_url=display.illustration_url,
            )
            appearance = connection.execute(
                "SELECT avatar_asset_id,appearance_version "
                "FROM character_instances WHERE character_id=?",
                (instance.character_id,),
            ).fetchone()
            data.update(dict(appearance))
            return data

    def characters(self, community_id, player_id):
        with self.database.read() as connection:
            self.repository.require_member(connection, community_id, ActorRef("player", player_id))
            result = []
            for instance in self.identity.instances.list(connection, community_id):
                data = asdict(instance)
                display = self.identity.display(
                    connection, community_id, ActorRef("character", instance.character_id)
                )
                data.update(
                    display_name=display.display_name,
                    avatar_url=display.avatar_url,
                    illustration_url=display.illustration_url,
                )
                appearance = connection.execute(
                    "SELECT avatar_asset_id,appearance_version "
                    "FROM character_instances WHERE character_id=?",
                    (instance.character_id,),
                ).fetchone()
                data.update(dict(appearance))
                result.append(data)
            return result
