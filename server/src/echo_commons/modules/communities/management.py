from echo_commons.infrastructure.database.connection import Database
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.management import PageOptions, read_page


class CommunityManagement:
    def __init__(self, database: Database) -> None:
        self.database = database
        self.repository = CommunityRepository()

    def communities(self, options: PageOptions, query: str = "") -> dict:
        query = query.strip()
        with self.database.read() as connection:
            return read_page(
                connection,
                "SELECT * FROM communities WHERE "
                "instr(lower(name),lower(?))>0 OR instr(lower(community_id),lower(?))>0",
                (query, query),
                scope={"query": "communities", "search": query},
                order=("created_at_utc", "community_id"),
                options=options,
            )

    def players(self, options: PageOptions) -> dict:
        with self.database.read() as connection:
            return read_page(
                connection,
                "SELECT * FROM players",
                (),
                scope={"query": "players"},
                order=("created_at_utc", "player_id"),
                options=options,
            )

    def members(self, community_id: str, options: PageOptions) -> dict:
        with self.database.read() as connection:
            self.repository.get(connection, community_id)
            return read_page(
                connection,
                "SELECT * FROM community_members WHERE community_id = ?",
                (community_id,),
                scope={"query": "members", "community_id": community_id},
                order=("actor_kind", "actor_id"),
                options=options,
            )

    def community(self, community_id: str):
        with self.database.read() as connection:
            return self.repository.get(connection, community_id)

    def player(self, player_id: str):
        with self.database.read() as connection:
            return self.repository.player(connection, player_id)
