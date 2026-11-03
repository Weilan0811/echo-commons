import sqlite3
from dataclasses import dataclass

from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.agents.contracts.output import (
    CharacterMessageProposal,
)
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.domain.instance import AvailabilityStatus
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.communities.domain import CommunityStatus
from echo_commons.modules.conversations.contracts import GameConversationAccess
from echo_commons.modules.conversations.domain.conversation import ConversationStatus
from echo_commons.modules.conversations.repositories.conversations import ConversationRepository
from echo_commons.modules.conversations.repositories.messages import MessageRepository
from echo_commons.modules.perspective.contracts import ObservationScope, PerspectiveReader
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import NotFoundError


@dataclass(frozen=True, slots=True)
class ReviewPolicy:
    max_thought_chars: int = 1000
    max_utterance_chars: int = 2000

    def __post_init__(self) -> None:
        if self.max_thought_chars < 1 or self.max_utterance_chars < 1:
            raise ValueError("Review length limits must be positive")

    def instructions(self) -> str:
        return (
            f"thought 最多 {self.max_thought_chars} 个字符；"
            f"utterance 最多 {self.max_utterance_chars} 个字符。"
        )


class ExpressionReview:
    def __init__(
        self,
        communities: CommunityReader,
        instances: InstanceReader,
        conversations: ConversationRepository,
        messages: MessageRepository,
        perspective: PerspectiveReader,
        policy: ReviewPolicy,
        game_access: GameConversationAccess | None = None,
    ) -> None:
        self.communities, self.instances, self.conversations = communities, instances, conversations
        self.messages, self.perspective, self.policy = messages, perspective, policy
        self.game_access = game_access

    def context(self, connection: sqlite3.Connection, snapshot: ContextSnapshot) -> str | None:
        scope = snapshot.scope
        community = self.communities.get(connection, scope.community_id)
        if community.status is not CommunityStatus.ACTIVE:
            return "community_paused"
        conversation = self.conversations.get(connection, scope.community_id, scope.conversation_id)
        if conversation.status is not ConversationStatus.ACTIVE:
            return "conversation_archived"
        try:
            member = self.conversations.current(
                connection, scope.conversation_id, ActorRef("character", scope.character_id)
            )
        except NotFoundError:
            return "member_left"
        if member.membership_id != scope.membership_id:
            return "member_left"
        if conversation.kind.value == "game" and (
            self.game_access is None
            or not self.game_access.can_send(
                connection, scope.community_id, scope.conversation_id, member.actor
            )
        ):
            return "source_replaced"
        instance = self.instances.get(connection, scope.community_id, scope.character_id)
        if instance.memory_status.value != "ready":
            return "character_memory_not_ready"
        if instance.availability_status is not AvailabilityStatus.AVAILABLE:
            return "character_unavailable"
        return None

    def expression(
        self,
        connection: sqlite3.Connection,
        snapshot: ContextSnapshot,
        proposal: CharacterMessageProposal,
    ) -> str | None:
        code = self.context(connection, snapshot)
        if code:
            return code
        scope = snapshot.scope
        if len(proposal.thought) > self.policy.max_thought_chars:
            return "thought_too_long"
        if len(proposal.utterance) > self.policy.max_utterance_chars:
            return "utterance_too_long"
        if proposal.reply_to is not None:
            try:
                reply_id = snapshot.reply_target(proposal.reply_to).message_id
            except ValueError:
                return "reply_target_unknown"
            try:
                target = self.messages.get(connection, scope.conversation_id, reply_id)
            except NotFoundError:
                return "reply_target_not_visible"
            observation = ObservationScope(
                scope.community_id,
                scope.conversation_id,
                ActorRef("character", scope.character_id),
                scope.observation_upper_sequence,
                scope.membership_id,
            )
            if not self.perspective.visible(connection, observation, target):
                return "reply_target_not_visible"
        return None
