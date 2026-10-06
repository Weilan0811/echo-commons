from dataclasses import dataclass
from datetime import datetime


@dataclass(frozen=True, slots=True)
class PendingMaterials:
    chars: int
    count: int
    oldest_at_utc: datetime
    reached_hard_limit: bool = False

    def due(self, now: datetime, *, target_chars: int, wait_seconds: float) -> bool:
        return self.count > 0 and (
            self.chars >= target_chars
            or self.reached_hard_limit
            or (now - self.oldest_at_utc).total_seconds() >= wait_seconds
        )
