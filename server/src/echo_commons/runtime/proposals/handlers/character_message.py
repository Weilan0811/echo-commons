from __future__ import annotations

from echo_commons.agents.contracts import CharacterMessageProposal, ProposalEnvelope, ProposalKind
from echo_commons.domain.proposals import ProposalDecision
from echo_commons.runtime.proposals.registry import ProposalReviewContext
from echo_commons.runtime.proposals.reviewer import ReviewCode, ReviewResult


class CharacterMessageHandler:
    """The first concrete reviewer; message-specific rules stay out of Runtime."""

    kind = ProposalKind.CHARACTER_MESSAGE

    def __init__(self, max_utterance_length: int = 2000, max_thought_length: int = 1000) -> None:
        self.max_utterance_length = max_utterance_length
        self.max_thought_length = max_thought_length

    def review(
        self,
        envelope: ProposalEnvelope,
        *,
        context: ProposalReviewContext,
    ) -> ReviewResult:
        if not isinstance(envelope.payload, CharacterMessageProposal):
            return ReviewResult(ProposalDecision.REJECTED, ReviewCode.INVALID_PAYLOAD)
        proposal = envelope.payload
        if (
            context.expected_character_id is None
            or proposal.character_id != context.expected_character_id
        ):
            return ReviewResult(ProposalDecision.REJECTED, ReviewCode.CHARACTER_MISMATCH)
        if len(proposal.thought) > self.max_thought_length:
            return ReviewResult(ProposalDecision.REJECTED, ReviewCode.THOUGHT_TOO_LONG)
        if not proposal.utterance.strip():
            return ReviewResult(ProposalDecision.REJECTED, ReviewCode.EMPTY_UTTERANCE)
        if len(proposal.utterance) > self.max_utterance_length:
            return ReviewResult(ProposalDecision.REJECTED, ReviewCode.UTTERANCE_TOO_LONG)
        return ReviewResult(ProposalDecision.APPROVED, ReviewCode.APPROVED)
