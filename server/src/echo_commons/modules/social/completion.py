from __future__ import annotations

import sqlite3
from collections import Counter
from datetime import datetime

from echo_commons.modules.social.continuation import ContinuationPolicy
from echo_commons.modules.social.domain import ParticipationStatus
from echo_commons.modules.social.events import turns_changed
from echo_commons.modules.social.repository import SocialRepository


class TurnCompletion:
    def __init__(self, social: SocialRepository) -> None:
        self.social = social

    def update(self, connection: sqlite3.Connection, turn_id: str, now: datetime) -> bool:
        turn = self.social.by_id(connection, turn_id)
        if turn.status not in ("pending", "running"):
            return True
        decisions = self.social.decisions(connection, turn_id)
        if any(decision.status is ParticipationStatus.SELECTED for decision in decisions):
            return False
        if turn.chain_id is not None:
            chain = self.social.chain(connection, turn.chain_id)
            spoken = any(item.outcome == "message" for item in decisions)
            reason = ContinuationPolicy.stop_reason(chain)
            if not spoken and reason is None and self.social.waiting(connection, turn_id):
                return False
            if spoken:
                self.social.close_candidates(connection, turn_id, "another_character_spoke", now)
                self.social.set_stop_reason(connection, turn_id, "message")
            else:
                reason = reason or (
                    "candidates_exhausted"
                    if any(item.selection_order is not None for item in decisions)
                    else "no_eligible_candidates"
                )
                self.social.close_candidates(connection, turn_id, reason, now)
                self.social.set_stop_reason(connection, turn_id, reason)
            if reason:
                self.social.stop_chain(connection, turn.chain_id, reason, now)
            decisions = self.social.decisions(connection, turn_id)
        self.social.finish(
            connection, turn_id, dict(Counter(decision.outcome for decision in decisions)), now
        )
        turns_changed(connection, turn_id)
        return True
