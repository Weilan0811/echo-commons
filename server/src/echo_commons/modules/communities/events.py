from echo_commons.shared.actors import ActorRef
from echo_commons.shared.realtime import EventReference


class CommunityEvents:
    def __init__(self, repository):
        self.repository = repository

    def require_member(self, connection, community_id: str, player_id: str):
        self.repository.get(connection, community_id)
        self.repository.require_member(connection, community_id, ActorRef("player", player_id))

    def project(self, connection, event: EventReference, player_id: str):
        self.require_member(connection, event.community_id, player_id)
        return {"community_id": event.community_id}
