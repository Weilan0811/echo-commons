from __future__ import annotations

from dataclasses import dataclass, field
from typing import TYPE_CHECKING, Protocol

if TYPE_CHECKING:
    from echo_server.agents.harness.tools import ToolResult

ProgressKey = tuple[str, ...]


class ToolProgressExtractor(Protocol):
    def __call__(self, result: ToolResult) -> tuple[ProgressKey, ...]:
        """Extract material identifiers returned by one tool call."""


@dataclass(frozen=True, slots=True)
class ProgressObservation:
    progressed: bool
    new_item_count: int
    no_progress_streak: int


@dataclass(slots=True)
class ToolProgressState:
    observed_keys: set[ProgressKey] = field(default_factory=set)
    no_progress_streak: int = 0

    def observe(self, keys: tuple[ProgressKey, ...]) -> ProgressObservation:
        unique_keys = tuple(dict.fromkeys(keys))
        new_keys = tuple(key for key in unique_keys if key not in self.observed_keys)
        self.observed_keys.update(unique_keys)
        if new_keys:
            self.no_progress_streak = 0
        else:
            self.no_progress_streak += 1
        return ProgressObservation(
            progressed=bool(new_keys),
            new_item_count=len(new_keys),
            no_progress_streak=self.no_progress_streak,
        )


__all__ = [
    "ProgressKey",
    "ProgressObservation",
    "ToolProgressExtractor",
    "ToolProgressState",
]
