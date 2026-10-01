from __future__ import annotations

import sqlite3

from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.conversations.contracts import ConversationReader, MessageReader
from echo_commons.modules.conversations.domain.conversation import Membership
from echo_commons.modules.conversations.domain.message import Message
from echo_commons.modules.perspective.contracts import ObservationScope
from echo_commons.modules.perspective.policy import can_observe
from echo_commons.shared.errors import NotFoundError


class ConversationPerspective:
    def __init__(
        self,
        communities: CommunityReader,
        conversations: ConversationReader,
        messages: MessageReader,
    ) -> None:
        self.communities, self.conversations, self.message_source = (
            communities,
            conversations,
            messages,
        )

    def memberships(
        self, connection: sqlite3.Connection, scope: ObservationScope
    ) -> tuple[Membership, ...]:
        self.communities.require_member(connection, scope.community_id, scope.actor)
        self.conversations.get(connection, scope.community_id, scope.conversation_id)
        memberships = tuple(
            member
            for member in self.conversations.members(
                connection, scope.conversation_id, current_only=False
            )
            if member.actor == scope.actor
            and (scope.membership_id is None or member.membership_id == scope.membership_id)
        )
        if not memberships:
            raise NotFoundError("Actor has no membership in this observation scope")
        return memberships

    def visible(
        self, connection: sqlite3.Connection, scope: ObservationScope, message: Message
    ) -> bool:
        return any(
            can_observe(message, membership, scope.upper_sequence)
            for membership in self.memberships(connection, scope)
        )

    def messages(
        self, connection: sqlite3.Connection, scope: ObservationScope, *, after: int = 0
    ) -> tuple[Message, ...]:
        memberships = self.memberships(connection, scope)
        found = []
        cursor = after
        while rows := self.message_source.scan(
            connection, scope.conversation_id, cursor, scope.upper_sequence, 256
        ):
            found.extend(
                message
                for message in rows
                if any(can_observe(message, member, scope.upper_sequence) for member in memberships)
            )
            cursor = rows[-1].sequence
        return tuple(found)
