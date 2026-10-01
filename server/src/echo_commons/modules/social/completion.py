from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime

from echo_commons.modules.social.domain import ParticipationStatus
from echo_commons.modules.social.repository import SocialRepository


class TurnCompletion:
    def __init__(self, social: SocialRepository) -> None:
        self.social = social

    def update(self, connection: sqlite3.Connection, turn_id: str, now: datetime) -> bool:
        decisions = self.social.decisions(connection, turn_id)
        if any(decision.status is ParticipationStatus.SELECTED for decision in decisions):
            return False
        self.social.finish(
            connection, turn_id, dict(Counter(decision.outcome for decision in decisions)), now
        )
        return True
