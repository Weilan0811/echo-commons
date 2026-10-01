from __future__ import annotations

from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class Candidate:
    character_id: str
    mentioned: bool
    last_spoke_at: datetime | None
    exclusion_reason: str | None = None


def choose(candidates: tuple[Candidate, ...], maximum: int) -> tuple[str, ...]:
    if maximum < 1:
        raise ValueError("Responder limit must be positive")
    eligible = (candidate for candidate in candidates if candidate.exclusion_reason is None)
    ordered = sorted(
        eligible,
        key=lambda item: (
            not item.mentioned,
            item.last_spoke_at is not None,
            item.last_spoke_at.isoformat() if item.last_spoke_at else "",
            item.character_id,
        ),
    )
    return tuple(candidate.character_id for candidate in ordered[:maximum])
