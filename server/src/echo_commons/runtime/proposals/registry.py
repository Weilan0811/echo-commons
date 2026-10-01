from __future__ import annotations

from dataclasses import dataclass
from typing import TYPE_CHECKING, Protocol
from uuid import UUID

from echo_commons.agents.contracts import ProposalEnvelope, ProposalKind
from echo_commons.domain.task import TaskStatus

if TYPE_CHECKING:
    from echo_commons.runtime.proposals.reviewer import ReviewResult


@dataclass(frozen=True, slots=True)
class ProposalReviewContext:
    """Authoritative T3 values used for deterministic common review."""

    expected_agent_id: str
    expected_agent_kind: str
    expected_character_id: str | None
    expected_context_version: str
    actual_context_version: str
    task_status: TaskStatus | str
    lease_owner: str | None
    worker_id: str
    lease_valid: bool
    proposal_processed: bool = False
    expected_invocation_id: UUID | None = None
    expected_invocation_purpose: str | None = None


class ProposalHandler(Protocol):
    """Review implementation for one registered Proposal kind."""

    kind: ProposalKind

    def review(
        self,
        envelope: ProposalEnvelope,
        *,
        context: ProposalReviewContext,
    ) -> ReviewResult: ...


class ProposalRegistry:
    """Map Proposal discriminators to isolated review/commit handlers."""

    def __init__(self, handlers: tuple[ProposalHandler, ...] = ()) -> None:
        self._handlers: dict[str, ProposalHandler] = {}
        for handler in handlers:
            self.register(handler)

    def register(self, handler: ProposalHandler) -> None:
        key = handler.kind.value
        if key in self._handlers:
            raise ValueError(f"proposal handler already registered: {key}")
        self._handlers[key] = handler

    def get(self, kind: ProposalKind | str) -> ProposalHandler | None:
        key = kind.value if isinstance(kind, ProposalKind) else kind
        return self._handlers.get(key)

    def require(self, kind: ProposalKind | str) -> ProposalHandler:
        handler = self.get(kind)
        if handler is None:
            key = kind.value if isinstance(kind, ProposalKind) else kind
            raise LookupError(f"proposal handler is not registered: {key}")
        return handler
