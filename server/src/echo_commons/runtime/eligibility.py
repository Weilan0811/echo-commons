from __future__ import annotations

from typing import Protocol

from echo_commons.domain.state import (
    EligibilityDecision,
    EligibilityRequest,
    evaluate_response_eligibility,
)


class ResponseEligibility(Protocol):
    """Pure response-eligibility port used by T2 and T3."""

    def evaluate(self, request: EligibilityRequest) -> EligibilityDecision:
        """Evaluate the supplied immutable state snapshot without I/O."""


class OfflineResponseEligibility:
    """Deterministic adapter for the currently implemented state rules."""

    def evaluate(self, request: EligibilityRequest) -> EligibilityDecision:
        return evaluate_response_eligibility(request)


__all__ = ["OfflineResponseEligibility", "ResponseEligibility"]
