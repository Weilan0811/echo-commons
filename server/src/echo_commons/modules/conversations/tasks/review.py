import sqlite3
from dataclasses import dataclass
from datetime import datetime

from echo_commons.agents.contracts.context import ContextSnapshot
from echo_commons.agents.contracts.invocation import AgentInvocation, InvocationPurpose
from echo_commons.agents.contracts.output import (
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
)
from echo_commons.agents.contracts.run import AgentRunResult, AgentRunStatus
from echo_commons.execution.contracts import TaskLease
from echo_commons.modules.characters.contracts import InstanceReader
from echo_commons.modules.characters.domain.instance import AvailabilityStatus
from echo_commons.modules.communities.contracts import CommunityReader
from echo_commons.modules.communities.domain import CommunityStatus
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


class ConversationReview:
    def __init__(
        self,
        communities: CommunityReader,
        instances: InstanceReader,
        conversations: ConversationRepository,
        messages: MessageRepository,
        perspective: PerspectiveReader,
        policy: ReviewPolicy,
    ) -> None:
        self.communities, self.instances, self.conversations = communities, instances, conversations
        self.messages, self.perspective, self.policy = messages, perspective, policy

    def check(
        self,
        connection: sqlite3.Connection,
        lease: TaskLease,
        task: sqlite3.Row,
        invocation: AgentInvocation,
        result: AgentRunResult,
        now: datetime,
    ) -> str | None:
        if (
            invocation.identity.purpose is not InvocationPurpose.CONVERSATION_REPLY
            or not isinstance(invocation.context, ContextSnapshot)
        ):
            return "invocation_identity_mismatch"
        scope = invocation.context.scope
        source = connection.execute(
            "SELECT t.status,c.status AS chain_status FROM social_turns t "
            "LEFT JOIN social_chains c ON c.chain_id=t.chain_id WHERE t.social_turn_id=?",
            (task["social_turn_id"],),
        ).fetchone()
        if source["status"] != "running" or source["chain_status"] not in (None, "active"):
            return "source_replaced"
        if (
            lease.task_id != invocation.scope.task_id
            or lease.attempt != invocation.identity.attempt
            or lease.trace_id != str(invocation.correlation.trace_id)
            or result.invocation_id != invocation.identity.invocation_id
            or result.agent_id != invocation.identity.agent_id
            or result.agent_kind != "character"
            or result.model_profile != invocation.execution_policy.model_profile
            or result.harness_version != invocation.execution_policy.harness_version
            or invocation.scope.source_kind != "social_turn"
            or invocation.scope.source_id != task["social_turn_id"]
            or task["snapshot_id"] != invocation.context_input.snapshot_id
            or task["character_id"] != invocation.scope.character_id
            or task["community_id"] != invocation.scope.community_id
            or task["conversation_id"] != scope.conversation_id
            or task["membership_id"] != scope.membership_id
        ):
            return "invocation_identity_mismatch"
        community = self.communities.get(connection, task["community_id"])
        if community.status is not CommunityStatus.ACTIVE:
            return "community_paused"
        conversation = self.conversations.get(
            connection, task["community_id"], task["conversation_id"]
        )
        if conversation.status is not ConversationStatus.ACTIVE:
            return "conversation_archived"
        try:
            member = self.conversations.current(
                connection, task["conversation_id"], ActorRef("character", task["character_id"])
            )
        except NotFoundError:
            return "member_left"
        if member.membership_id != task["membership_id"]:
            return "member_left"
        instance = self.instances.get(connection, task["community_id"], task["character_id"])
        if instance.memory_status.value != "ready":
            return "character_memory_not_ready"
        if instance.availability_status is not AvailabilityStatus.AVAILABLE:
            return "character_unavailable"
        if result.status is AgentRunStatus.NO_PROPOSAL:
            return None if result.output is None else "unexpected_silent_output"
        if result.status is not AgentRunStatus.COMPLETED or result.output is None:
            return "invalid_agent_result"
        if result.output.contract != CHARACTER_MESSAGE_CONTRACT or not isinstance(
            result.output.payload, CharacterMessageProposal
        ):
            return "invalid_output_contract"
        proposal = result.output.payload
        if len(proposal.thought) > self.policy.max_thought_chars:
            return "thought_too_long"
        if len(proposal.utterance) > self.policy.max_utterance_chars:
            return "utterance_too_long"
        if proposal.reply_to is not None:
            try:
                reply_id = invocation.context.reply_target(proposal.reply_to).message_id
            except ValueError:
                return "reply_target_unknown"
            try:
                target = self.messages.get(connection, task["conversation_id"], reply_id)
            except NotFoundError:
                return "reply_target_not_visible"
            observation = ObservationScope(
                task["community_id"],
                task["conversation_id"],
                member.actor,
                scope.observation_upper_sequence,
                member.membership_id,
            )
            if not self.perspective.visible(connection, observation, target):
                return "reply_target_not_visible"
        return None
