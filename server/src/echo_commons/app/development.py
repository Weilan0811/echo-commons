import sqlite3
from contextlib import closing
from pathlib import Path

from pydantic import BaseModel, ConfigDict

from echo_commons.app.composition import Application
from echo_commons.modules.conversations.domain.conversation import ConversationKind
from echo_commons.shared.actors import ActorRef


class ExamplePlayer(BaseModel):
    model_config = ConfigDict(extra="forbid")
    player_id: str
    display_name: str


class ExampleCharacter(BaseModel):
    model_config = ConfigDict(extra="forbid")
    character_id: str
    blueprint_id: str


class ExampleCommunity(BaseModel):
    model_config = ConfigDict(extra="forbid")
    community_id: str
    name: str
    timezone: str
    players: tuple[ExamplePlayer, ...]
    characters: tuple[ExampleCharacter, ...]
    conversation_id: str


def initialize_example(application: Application, example: ExampleCommunity) -> dict:
    community = application.communities.create(
        example.name, example.timezone, community_id=example.community_id
    )
    actors = []
    for player in example.players:
        application.communities.register_player(player.display_name, player_id=player.player_id)
        actor = ActorRef("player", player.player_id)
        application.communities.join(community.community_id, actor)
        actors.append(actor)
    for character in example.characters:
        application.characters.create(
            community.community_id,
            character.blueprint_id,
            character_id=character.character_id,
        )
        actors.append(ActorRef("character", character.character_id))
    conversation = application.conversations.create(
        community.community_id,
        ConversationKind.GROUP,
        tuple(actors),
        conversation_id=example.conversation_id,
    )
    return {
        "community_id": community.community_id,
        "conversation_id": conversation.conversation_id,
        "actors": [{"kind": actor.kind.value, "actor_id": actor.actor_id} for actor in actors],
    }


def inspect_database(application: Application) -> dict:
    with application.database.read() as connection:
        version = connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
        counts = {
            table: connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0]
            for table in (
                "communities",
                "players",
                "character_instances",
                "conversations",
                "messages",
            )
        }
    return {
        "database_path": str(application.database.path.resolve()),
        "schema_version": version,
        "counts": counts,
        "blueprints": sorted(application.catalog.blueprints),
        "model_profile": application.models.active_profile,
        "model_configured": (
            application.models.credential_for(application.models.resolve()) is not None
        ),
        "strong_enabled": application.models.strong_enabled,
        "model_routes": {
            task: {
                "profile": (route := application.models.route_for(task)).resolved_profile,
                "entry_id": (entry := application.models.resolve(route.resolved_profile)).entry_id,
                "vendor": entry.model_vendor,
                "model": entry.model,
                "credential_ref": entry.credential_ref,
                "configured": application.models.credential_for(entry) is not None,
            }
            for task in (
                "conversation_reply", "character_authoring", "character_interview_review", "reflection"
            )
        },
    }


def export_database(application: Application, destination: Path) -> dict:
    destination = destination.resolve()
    destination.parent.mkdir(parents=True, exist_ok=True)
    # 排他创建保证已有导出文件不会被覆盖；SQLite backup 保存一致的数据库副本。
    with destination.open("xb"):
        pass
    try:
        with (
            closing(application.database.connect()) as source,
            closing(sqlite3.connect(destination)) as target,
        ):
            source.backup(target)
    except Exception:
        destination.unlink()
        raise
    return {"export_path": str(destination)}
