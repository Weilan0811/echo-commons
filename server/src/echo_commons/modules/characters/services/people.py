from datetime import UTC, datetime

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.characters.domain.authoring import AuthoringContent
from echo_commons.modules.characters.domain.people import PersonRegistration
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, NotFoundError


class CharacterPeople:
    def __init__(self, database, initialization):
        self.database = database
        self.initialization = initialization

    @staticmethod
    def require(connection, person_id, player_id):
        row = connection.execute(
            "SELECT p.* FROM character_people p WHERE p.person_id=? AND "
            "(p.owner_player_id=? OR EXISTS (SELECT 1 FROM character_person_bindings b "
            "JOIN community_members m ON m.community_id=b.community_id "
            "WHERE b.person_id=p.person_id AND m.actor_kind='player' AND m.actor_id=?))",
            (str(person_id), player_id, player_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Person is unavailable in this author's library")
        return row

    @classmethod
    def validate_materials(cls, connection, player_id, content):
        if content.person_id:
            cls.require(connection, content.person_id, player_id)
        for item in content.relationships:
            target = cls.require(connection, item.target_person_id, player_id)
            if str(item.target_person_id) == str(content.person_id):
                raise ConflictError("A relationship must refer to another person")
            if item.target_name != target["display_name"]:
                raise ConflictError("Relationship name must match the selected person")

    def register(self, request: PersonRegistration):
        with self.database.transaction() as connection:
            CommunityRepository().player(connection, request.player_id)
            existing = connection.execute(
                "SELECT * FROM character_people WHERE person_id=?", (str(request.person_id),)
            ).fetchone()
            if existing and (
                existing["owner_player_id"],
                existing["display_name"],
                existing["description"],
            ) != (request.player_id, request.display_name, request.description):
                raise ConflictError("Person ID already has a different registration")
            connection.execute(
                "INSERT INTO character_people VALUES (?,?,?,?,?) ON CONFLICT(person_id) DO NOTHING",
                (
                    str(request.person_id),
                    request.player_id,
                    request.display_name,
                    request.description,
                    utc_text(datetime.now(UTC)),
                ),
            )
        return request.model_dump(mode="json")

    def list(self, player_id):
        with self.database.read() as connection:
            CommunityRepository().player(connection, player_id)
            return [
                dict(
                    person_id=row["person_id"],
                    player_id=row["owner_player_id"],
                    display_name=row["display_name"],
                    description=row["description"],
                )
                for row in connection.execute(
                    "SELECT p.* FROM character_people p WHERE p.owner_player_id=? OR EXISTS "
                    "(SELECT 1 FROM character_person_bindings b JOIN community_members m "
                    "ON m.community_id=b.community_id WHERE b.person_id=p.person_id "
                    "AND m.actor_kind='player' AND m.actor_id=?) "
                    "ORDER BY display_name,person_id",
                    (player_id, player_id),
                )
            ]

    @classmethod
    def bind_in(cls, connection, community, player, person, actor):
        cls.require(connection, person, player)
        communities = CommunityRepository()
        communities.require_member(connection, community, ActorRef("player", player))
        communities.require_member(connection, community, actor)
        if actor.kind.value == "player" and actor.actor_id != player:
            raise ConflictError("Only the player can bind their own identity")
        if actor.kind.value == "character":
            row = connection.execute(
                "SELECT b.owner_player_id,b.materials_json FROM character_instances c "
                "LEFT JOIN custom_character_blueprints b USING(blueprint_id) "
                "WHERE c.community_id=? AND c.character_id=?",
                (community, actor.actor_id),
            ).fetchone()
            if row and row["owner_player_id"] is not None and row["owner_player_id"] != player:
                raise ConflictError("Character belongs to another author")
            if row and row["materials_json"] is not None:
                content = AuthoringContent.model_validate_json(row["materials_json"])
                if any(str(item.target_person_id) == str(person) for item in content.relationships):
                    raise ConflictError(
                        "A character cannot bind a person used as its relationship target"
                    )
        existing = connection.execute(
            "SELECT * FROM character_person_bindings WHERE community_id=? AND "
            "(person_id=? OR (actor_kind=? AND actor_id=?))",
            (community, str(person), actor.kind.value, actor.actor_id),
        ).fetchall()
        if any(
            (row["person_id"], row["actor_kind"], row["actor_id"])
            != (str(person), actor.kind.value, actor.actor_id)
            for row in existing
        ):
            raise ConflictError("This person or member already has a different binding")
        connection.execute(
            "INSERT INTO character_person_bindings VALUES (?,?,?,?) "
            "ON CONFLICT(community_id,person_id) DO NOTHING",
            (community, str(person), actor.kind.value, actor.actor_id),
        )

    def bind(self, community, request):
        actor = ActorRef(request.actor_kind, request.actor_id)
        with self.database.transaction() as connection:
            self.bind_in(connection, community, request.player_id, request.person_id, actor)
            self.initialization.apply(connection, community, datetime.now(UTC))
        return request.model_dump(mode="json") | {"community_id": community}

    def bindings(self, community, player):
        with self.database.read() as connection:
            CommunityRepository().require_member(connection, community, ActorRef("player", player))
            return [
                dict(row)
                for row in connection.execute(
                    "SELECT person_id,actor_kind,actor_id FROM character_person_bindings "
                    "WHERE community_id=? ORDER BY person_id",
                    (community,),
                )
            ]
