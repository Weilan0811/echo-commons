import re

from echo_commons.execution.clock import utc_now
from echo_commons.modules.assets.repository import AssetRepository
from echo_commons.modules.communities.repository import CommunityRepository
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError
from echo_commons.shared.realtime import EventKind, EventReference, EventSource, record_event


def set_cover(connection, community_id, player_id, kind, reference):
    if (kind is None) != (reference is None):
        raise ValueError("Cover kind and reference must be provided together")
    if kind not in (None, "preset", "asset"):
        raise ValueError("Unknown cover kind")
    if kind == "preset" and not re.fullmatch(r"[A-Za-z0-9][A-Za-z0-9_.-]{0,119}", reference):
        raise ValueError("Invalid preset key")
    AssetRepository().bind(
        connection,
        "community",
        community_id,
        reference if kind == "asset" else None,
        player_id,
        "community_cover",
    )
    connection.execute(
        "UPDATE communities SET cover_kind=?,cover_ref=? WHERE community_id=?",
        (kind, reference, community_id),
    )


def update_cover(database, community_id, request):
    repository = CommunityRepository()
    with database.transaction() as connection:
        repository.require_member(connection, community_id, ActorRef("player", request.player_id))
        current = repository.get(connection, community_id)
        if current.state_version != request.expected_version:
            raise ConflictError("Community state version has changed")
        if (current.cover_kind, current.cover_ref) != (request.cover_kind, request.cover_ref):
            set_cover(
                connection, community_id, request.player_id, request.cover_kind, request.cover_ref
            )
            connection.execute(
                "UPDATE communities SET state_version=state_version+1,"
                "updated_at_utc=? WHERE community_id=?",
                (utc_now().isoformat(), community_id),
            )
            record_event(
                connection,
                EventReference(
                    EventKind.COMMUNITY_APPEARANCE,
                    community_id,
                    community_id,
                    EventSource.COMMUNITY,
                    community_id,
                ),
            )
        return repository.get(connection, community_id)
