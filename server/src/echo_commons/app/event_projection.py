from echo_commons.app.event_schemas import EVENT_DATA_MODELS
from echo_commons.modules.communities.events import CommunityEvents
from echo_commons.modules.conversations.services.events import ConversationEvents
from echo_commons.modules.social.events import SocialEvents
from echo_commons.shared.errors import NotFoundError
from echo_commons.shared.realtime import EventReference, EventSource


class EventProjection:
    def __init__(
        self, conversations: ConversationEvents, social: SocialEvents, communities: CommunityEvents
    ):
        self.conversations, self.social, self.communities = conversations, social, communities

    def require_member(self, connection, community_id, player_id):
        self.communities.require_member(connection, community_id, player_id)

    def project(self, connection, event: EventReference, player_id: str):
        projector = (
            self.communities
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
