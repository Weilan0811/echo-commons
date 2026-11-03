from __future__ import annotations

import sqlite3

from echo_commons.modules.characters.contracts import CharacterIdentityReader
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.conversations.contracts import ConversationReader
from echo_commons.modules.perspective.contracts import (
    ConversationBoundary,
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
        self.activities = None

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

    def freeze(
        self,
        connection,
        community_id,
        actor,
        observed_at,
        *,
        conversation_id=None,
        upper_sequence=None,
    ) -> tuple[ConversationBoundary, ...]:
        self.community.require_member(connection, community_id, actor)
        scenes = []
        for conversation in self.conversations.for_actor(connection, community_id, actor):
            members = tuple(
                member
                for member in self.conversations.members(
                    connection, conversation.conversation_id, current_only=False
                )
                if member.joined_at_utc <= observed_at
            )
            own = tuple(member.membership_id for member in members if member.actor == actor)
            if not own:
                continue
            others = tuple(
                dict.fromkeys(
                    self.actor_name(connection, community_id, member.actor)
                    for member in members
                    if member.actor != actor
                )
            )
            name = (
                "与" + "、".join(others) + "的私聊"
                if conversation.kind == "direct"
                else "群聊（" + "、".join(others) + "）"
            )
            upper = (
                upper_sequence
                if conversation.conversation_id == conversation_id
                else conversation.next_sequence - 1
            )
            scenes.append(
                ConversationBoundary(
                    conversation_id=conversation.conversation_id,
                    kind=conversation.kind.value,
                    name=name,
                    upper_sequence=upper,
                    membership_ids=own,
                )
            )
        return tuple(scenes)

    def experiences(self, connection, community_id, actor, boundaries, observed_at):
        messages = {}
        for scene in boundaries:
            for membership_id in scene.membership_ids:
                for message in self.perspective.messages(
                    connection,
                    ObservationScope(
                        community_id,
                        scene.conversation_id,
                        actor,
                        scene.upper_sequence,
                        membership_id,
                    ),
                ):
                    if message.created_at_utc <= observed_at:
                        messages[message.message_id] = message
        return tuple(
            sorted(
                messages.values(),
                key=lambda item: (
                    item.created_at_utc,
                    item.conversation_id,
                    item.sequence,
                    item.message_id,
                ),
            )
        )
