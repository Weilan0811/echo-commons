from __future__ import annotations

import sqlite3

from echo_commons.modules.characters.contracts import CharacterIdentityReader
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.perspective.contracts import (
    Observation,
    ObservationScope,
    PerspectiveReader,
    PublicParticipant,
)
from echo_commons.shared.actors import ActorKind, ActorRef


class WorldPerspective:
    def __init__(
        self,
        community: CommunityReader,
        characters: CharacterIdentityReader,
        conversations: ConversationReader,
        perspective: PerspectiveReader,
    ) -> None:
        self.community, self.characters, self.conversations, self.perspective = (
            community,
            characters,
            conversations,
            perspective,
        )

    def actor_name(self, connection: sqlite3.Connection, community_id: str, actor: ActorRef) -> str:
        self.community.require_member(connection, community_id, actor)
        if actor.kind is ActorKind.PLAYER:
            return self.community.player(connection, actor.actor_id).display_name
        return self.characters.name(connection, community_id, actor.actor_id)

    def observe(self, connection: sqlite3.Connection, scope: ObservationScope) -> Observation:
        messages = self.perspective.messages(connection, scope)
        participants = tuple(
            PublicParticipant(
                member.actor,
                self.actor_name(connection, scope.community_id, member.actor),
                member.membership_id,
            )
            for member in self.conversations.members(
                connection, scope.conversation_id, current_only=False
            )
            if member.joined_after_sequence <= scope.upper_sequence
            and (member.left_at_sequence is None or member.left_at_sequence > scope.upper_sequence)
        )
        return Observation(messages, participants)
