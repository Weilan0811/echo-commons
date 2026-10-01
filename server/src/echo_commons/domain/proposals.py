from __future__ import annotations

from enum import StrEnum


class ProposalDecision(StrEnum):
    APPROVED = "approved"
    REJECTED = "rejected"
    EXPIRED = "expired"
