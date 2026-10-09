from echo_commons.modules.conversations.domain.message import Message
from echo_commons.shared.realtime import EventKind, EventReference, EventSource, record_event


def message_created(connection, message: Message):
    for kind in (EventKind.MESSAGE, EventKind.SUMMARY):
        record_event(
            connection,
            EventReference(
                kind,
                message.community_id,
                message.conversation_id,
                EventSource.MESSAGE,
                message.message_id,
            ),
        )


def conversation_changed(connection, conversation_id: str, *, leaving_player: str | None = None):
    community_id = connection.execute(
        "SELECT community_id FROM conversations WHERE conversation_id=?",
        (conversation_id,),
    ).fetchone()[0]
    audience = {
        row[0]
        for row in connection.execute(
            "SELECT actor_id FROM conversation_memberships WHERE conversation_id=? "
            "AND actor_kind='player' AND left_at_utc IS NULL",
            (conversation_id,),
        )
    }
    if leaving_player is not None:
        audience.add(leaving_player)
    for kind in (EventKind.MEMBERS, EventKind.SUMMARY):
        record_event(
            connection,
            EventReference(
                kind,
                community_id,
                conversation_id,
                EventSource.CONVERSATION,
                conversation_id,
                tuple(sorted(audience)),
            ),
        )


class ConversationEvents:
    def __init__(self, query):
        self.query = query

    def project(self, connection, event: EventReference, player_id: str):
        _, scope = self.query.scope(connection, event.object_id, player_id)
        data = {"community_id": event.community_id, "conversation_id": event.object_id}
        if event.source is EventSource.MESSAGE:
            message = self.query.messages.get(connection, event.object_id, event.source_id)
            if not self.query.perspective.visible(connection, scope, message):
                return None
            if event.kind is EventKind.MESSAGE:
                data["message"] = self.query.view(connection, scope, message)
        elif event.source is EventSource.READ:
            if event.source_id != player_id:
                return None
        elif player_id not in event.audience:
            return None
        return data
