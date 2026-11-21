from __future__ import annotations

import math
import random
from dataclasses import dataclass
from datetime import datetime
from typing import Protocol

from echo_commons.modules.social.settings import ParticipationBalance


@dataclass(frozen=True, slots=True)
class Candidate:
    character_id: str
    mentioned: bool
    last_spoke_at: datetime | None
    exclusion_reason: str | None = None
    chain_attempts: int = 0
    replied_to: bool = False


def choose(candidates: tuple[Candidate, ...], maximum: int) -> tuple[str, ...]:
    if maximum < 1:
        raise ValueError("Responder limit must be positive")
    eligible = (candidate for candidate in candidates if candidate.exclusion_reason is None)
    ordered = sorted(
        eligible,
        key=lambda item: (
            not (item.mentioned or item.replied_to),
            item.chain_attempts,
            item.last_spoke_at is not None,
            item.last_spoke_at.isoformat() if item.last_spoke_at else "",
            item.character_id,
        ),
    )
    return tuple(candidate.character_id for candidate in ordered[:maximum])


class ParticipationPolicy(Protocol):
    version: str

    def select(self, candidates: tuple[Candidate, ...]) -> str | None: ...


class RuleBasedParticipationPolicy:
    version = "rules-v1"

    def select(self, candidates: tuple[Candidate, ...]) -> str | None:
        selected = choose(candidates, 1)
        return selected[0] if selected else None


@dataclass(frozen=True, slots=True)
class ScoredSelection:
    selected: str | None
    base_probabilities: dict[str, float]
    probabilities: dict[str, float]
    corrections: dict[str, float]


def choose_scored(
    scores: dict[str, float],
    threshold: float,
    temperature: float,
    *,
    shares: dict[str, tuple[float, float]] | None = None,
    balance: ParticipationBalance | None = None,
) -> ScoredSelection:
    eligible = {key: score for key, score in scores.items() if score >= threshold}
    if not eligible:
        return ScoredSelection(None, {}, {}, {})
    peak = max(eligible.values())
    weights = {key: math.exp((score - peak) / temperature) for key, score in eligible.items()}
    total = sum(weights.values())
    base = {key: weight / total for key, weight in weights.items()}
    balance = balance or ParticipationBalance()
    shares = shares or {}
    corrections = {
        key: 1
        + balance.correction_limit
        * math.tanh((shares.get(key, (0, 0))[0] - shares.get(key, (0, 0))[1]) / balance.gap_scale)
        for key in base
    }
    corrected = {key: base[key] * corrections[key] for key in base}
    probabilities = {key: weight / sum(corrected.values()) for key, weight in corrected.items()}
    selected = random.choices(list(probabilities), weights=list(probabilities.values()), k=1)[0]
    return ScoredSelection(selected, base, probabilities, corrections)
