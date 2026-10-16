from echo_commons.app.event_schemas import EVENT_DATA_MODELS
from echo_commons.app.games.events import GameEvents
from echo_commons.modules.communities.events import CommunityEvents
from echo_commons.modules.conversations.services.events import ConversationEvents
from echo_commons.modules.social.events import SocialEvents
from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.realtime import EventReference, EventSource


class EventProjection:
    def __init__(
        self,
        conversations: ConversationEvents,
        social: SocialEvents,
        communities: CommunityEvents,
        games: GameEvents,
    ):
        self.conversations, self.social, self.communities = conversations, social, communities
        self.games = games

    def require_member(self, connection, community_id, player_id):
        self.communities.require_member(connection, community_id, player_id)

    def project(self, connection, event: EventReference, player_id: str):
        if event.source is EventSource.CHARACTER:
            try:
                self.communities.require_member(connection, event.community_id, player_id)
            except NotFoundError:
                return None
            if (
                connection.execute(
                    "SELECT 1 FROM character_instances WHERE community_id=? AND character_id=?",
                    (event.community_id, event.object_id),
                ).fetchone()
                is None
            ):
                return None
            return (
                EVENT_DATA_MODELS[event.kind]
                .model_validate(
                    {
                        "community_id": event.community_id,
                        "character_id": event.object_id,
                    }
                )
                .model_dump(mode="json")
            )
        projector = (
            self.games
            if event.source is EventSource.GAME
            else self.communities
            if event.source is EventSource.COMMUNITY
            else self.social
            if event.source is EventSource.TURN
            else self.conversations
        )
        try:
            data = projector.project(connection, event, player_id)
            return (
                EVENT_DATA_MODELS[event.kind].model_validate(data).model_dump(mode="json")
                if data is not None
                else None
            )
        except NotFoundError:
            return None
