import sqlite3
from collections import Counter
from datetime import datetime

from echo_commons.modules.social.contracts import TaskCancellationPort
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
        if any(item.status is ParticipationStatus.SELECTED for item in decisions):
            return False
        self.social.finish(
            connection, turn_id, dict(Counter(item.outcome for item in decisions)), now
        )
        turns_changed(connection, turn_id)
        return True

    def close_round(self, connection, chain, reason, now, tasks: TaskCancellationPort) -> None:
        for row in connection.execute(
            "SELECT social_turn_id FROM social_turns WHERE chain_id=? AND status='pending'",
            (chain.chain_id,),
        ).fetchall():
            tasks.cancel_turn(connection, row[0], reason, now)
            self.social.cancel_turn(connection, row[0], reason, now)
        self.social.stop_chain(connection, chain.chain_id, reason, now)
        for row in connection.execute(
            "SELECT social_turn_id FROM social_turns WHERE chain_id=?", (chain.chain_id,)
        ):
            turns_changed(connection, row[0])
