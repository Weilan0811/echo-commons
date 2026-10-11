from echo_commons.modules.assets.repository import AssetRepository
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, NotFoundError
from echo_commons.shared.realtime import EventKind, EventReference, EventSource, record_event


def update_avatar(database, community_id, character_id, request):
    with database.transaction() as connection:
        CommunityRepository().require_member(
            connection, community_id, ActorRef("player", request.player_id)
        )
        row = connection.execute(
            "SELECT * FROM character_instances WHERE community_id=? AND character_id=?",
            (community_id, character_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Character does not belong to this community")
        if row["appearance_version"] != request.expected_version:
            raise ConflictError("Character appearance version has changed")
        if row["avatar_asset_id"] != request.avatar_asset_id:
            AssetRepository().bind(
                connection,
                "character",
                character_id,
                request.avatar_asset_id,
                request.player_id,
                "character_avatar",
            )
            connection.execute(
                "UPDATE character_instances SET avatar_asset_id=?,"
                "appearance_version=appearance_version+1 WHERE character_id=?",
                (request.avatar_asset_id, character_id),
            )
            record_event(
                connection,
                EventReference(
                    EventKind.CHARACTER_APPEARANCE,
                    community_id,
                    character_id,
                    EventSource.CHARACTER,
                    character_id,
                ),
            )
