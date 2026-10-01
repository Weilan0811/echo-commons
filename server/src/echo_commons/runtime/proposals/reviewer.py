from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum

from echo_commons.agents.contracts import InvocationOrigin, ProposalEnvelope
from echo_commons.domain.proposals import ProposalDecision
from echo_commons.runtime.proposals.registry import ProposalRegistry, ProposalReviewContext


class ReviewCode(StrEnum):
    APPROVED = "approved"
    UNKNOWN_PROPOSAL_KIND = "unknown_proposal_kind"
    INVALID_PAYLOAD = "invalid_payload"
    INVOCATION_MISMATCH = "invocation_mismatch"
    INVOCATION_PURPOSE_MISMATCH = "invocation_purpose_mismatch"
    CHARACTER_MISMATCH = "character_mismatch"
    THOUGHT_TOO_LONG = "thought_too_long"
    EMPTY_UTTERANCE = "empty_utterance"
    UTTERANCE_TOO_LONG = "utterance_too_long"
    PROPOSAL_ALREADY_PROCESSED = "proposal_already_processed"
    TASK_NOT_PROCESSING = "task_not_processing"
    LEASE_NOT_OWNED = "lease_not_owned"
    LEASE_EXPIRED = "lease_expired"
    CONTEXT_EXPIRED = "context_expired"


@dataclass(frozen=True, slots=True)
class ReviewResult:
    decision: ProposalDecision
    code: ReviewCode


class ProposalReviewer:
    """Review common conversation guards, then dispatch by Proposal kind."""

    def __init__(self, registry: ProposalRegistry | None = None) -> None:
        self.registry = registry or ProposalRegistry()

    def review(
        self,
        envelope: ProposalEnvelope,
        *,
        context: ProposalReviewContext,
    ) -> ReviewResult:
        if context.proposal_processed:
            return ReviewResult(ProposalDecision.REJECTED, ReviewCode.PROPOSAL_ALREADY_PROCESSED)
        if str(context.task_status) != "processing":
            return ReviewResult(ProposalDecision.EXPIRED, ReviewCode.TASK_NOT_PROCESSING)
        if context.lease_owner != context.worker_id:
            return ReviewResult(ProposalDecision.EXPIRED, ReviewCode.LEASE_NOT_OWNED)
        if not context.lease_valid:
            return ReviewResult(ProposalDecision.EXPIRED, ReviewCode.LEASE_EXPIRED)
        if context.expected_context_version != context.actual_context_version:
            return ReviewResult(ProposalDecision.EXPIRED, ReviewCode.CONTEXT_EXPIRED)
        if context.expected_invocation_purpose is not None:
            purpose = getattr(
                context.expected_invocation_purpose,
                "value",
                context.expected_invocation_purpose,
            )
            expected_kind = "character_message" if purpose == "conversation_reply" else None
            if expected_kind is None or envelope.kind.value != expected_kind:
                return ReviewResult(
                    ProposalDecision.REJECTED,
                    ReviewCode.INVOCATION_PURPOSE_MISMATCH,
                )
        if context.expected_invocation_id is not None and (
            not isinstance(envelope.origin, InvocationOrigin)
            or envelope.origin.invocation_id != context.expected_invocation_id
        ):
            return ReviewResult(ProposalDecision.REJECTED, ReviewCode.INVOCATION_MISMATCH)
        handler = self.registry.get(envelope.kind)
        if handler is None:
            return ReviewResult(ProposalDecision.REJECTED, ReviewCode.UNKNOWN_PROPOSAL_KIND)
        return handler.review(envelope, context=context)


__all__ = ["ProposalReviewer", "ReviewCode", "ReviewResult"]
