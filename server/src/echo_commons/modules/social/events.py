from echo_commons.modules.perspective.contracts import ObservationScope
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.realtime import EventKind, EventReference, EventSource, record_event


def turns_changed(connection, turn_id: str):
    row = connection.execute(
        "SELECT community_id,conversation_id FROM social_turns WHERE social_turn_id=?",
        (turn_id,),
    ).fetchone()
    record_event(
        connection,
        EventReference(
            EventKind.TURNS,
            row[0],
            row[1],
            EventSource.TURN,
            turn_id,
        ),
    )


class SocialEvents:
    def __init__(self, query):
        self.query = query

    def project(self, connection, event: EventReference, player_id: str):
        conversation = self.query.conversations.get(
            connection,
            event.community_id,
            event.object_id,
        )
        scope = ObservationScope(
            event.community_id,
            event.object_id,
            ActorRef("player", player_id),
            conversation.next_sequence - 1,
        )
        if not self.query.visible(connection, event.source_id, scope):
            return None
        return {"community_id": event.community_id, "conversation_id": event.object_id}
