"""Process-local, provider-grouped model usage accounting."""

from __future__ import annotations

from dataclasses import dataclass

from echo_server.agents.contracts.run import UsageSummary


@dataclass(frozen=True, slots=True)
class ProviderUsageTracker:
    """Mutable-by-replacement usage tracker owned by one Gateway instance."""

    totals: dict[str, UsageSummary]

    def __init__(self) -> None:
        object.__setattr__(self, "totals", {})

    def record(self, provider: str, usage: UsageSummary) -> UsageSummary:
        current = self.totals.get(provider, UsageSummary())
        updated = current.add(
            usage.model_copy(update={"model_request_count": max(1, usage.model_request_count)})
        )
        self.totals[provider] = updated
        return updated

    def snapshot(self) -> dict[str, UsageSummary]:
        return dict(self.totals)
