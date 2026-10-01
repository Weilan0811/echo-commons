from __future__ import annotations

import json
import sqlite3
from datetime import datetime

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.social.domain import ParticipationDecision, SocialTurn, TurnStatus
from echo_commons.shared.errors import NotFoundError


class SocialRepository:
    def running(self, connection: sqlite3.Connection, conversation_id: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM social_turns WHERE conversation_id = ? AND status = 'running'",
                (conversation_id,),
            ).fetchone()
            is not None
        )

    def add(
        self, connection: sqlite3.Connection, turn: SocialTurn, batch_ids: tuple[str, ...]
    ) -> None:
        connection.execute(
            "INSERT INTO social_turns VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                turn.social_turn_id,
                turn.community_id,
                turn.conversation_id,
                json.dumps(turn.audience, separators=(",", ":")),
                turn.visibility,
                turn.observation_max_sequence,
                turn.membership_version,
                turn.status.value,
                None,
                utc_text(turn.created_at_utc),
                None,
            ),
        )
        connection.executemany(
            "INSERT INTO social_turn_batches VALUES (?, ?, ?)",
            [(turn.social_turn_id, batch, ordinal) for ordinal, batch in enumerate(batch_ids)],
        )

    def decision(self, connection: sqlite3.Connection, decision: ParticipationDecision) -> None:
        connection.execute(
            "INSERT INTO participation_decisions VALUES (?, ?, ?, ?, ?, ?, ?)",
            (
                decision.social_turn_id,
                decision.character_id,
                decision.reason_code,
                decision.selection_order,
                decision.status.value,
                decision.outcome,
                utc_text(decision.updated_at_utc),
            ),
        )

    def get(self, connection: sqlite3.Connection, community_id: str, turn_id: str) -> SocialTurn:
        row = connection.execute(
            "SELECT * FROM social_turns WHERE community_id = ? AND social_turn_id = ?",
            (community_id, turn_id),
        ).fetchone()
        if row is None:
            raise NotFoundError("Social turn does not exist in this community")
        return SocialTurn(
            row["social_turn_id"],
            row["community_id"],
            row["conversation_id"],
            tuple(json.loads(row["audience_json"])),
            row["visibility"],
            row["observation_max_sequence"],
            row["membership_version"],
            TurnStatus(row["status"]),
            utc_datetime(row["created_at_utc"]),
            utc_datetime(row["completed_at_utc"]) if row["completed_at_utc"] else None,
        )

    def decisions(
        self, connection: sqlite3.Connection, turn_id: str
    ) -> tuple[ParticipationDecision, ...]:
        return tuple(
            ParticipationDecision(
                row["social_turn_id"],
                row["character_id"],
                row["reason_code"],
                row["selection_order"],
                row["status"],
                row["outcome"],
                utc_datetime(row["updated_at_utc"]),
            )
            for row in connection.execute(
                "SELECT * FROM participation_decisions WHERE social_turn_id = ? "
                "ORDER BY selection_order, character_id",
                (turn_id,),
            )
        )

    def finish(
        self, connection: sqlite3.Connection, turn_id: str, summary: dict[str, int], now: datetime
    ) -> None:
        connection.execute(
            "UPDATE social_turns SET status = 'completed', completed_at_utc = ?, "
            "completion_json = ? WHERE social_turn_id = ? AND status = 'running'",
            (utc_text(now), json.dumps(summary, separators=(",", ":")), turn_id),
        )

    def complete_participation(
        self,
        connection: sqlite3.Connection,
        turn_id: str,
        character_id: str,
        status: str,
        outcome: str,
        now: datetime,
    ) -> None:
        connection.execute(
            "UPDATE participation_decisions SET status = ?, outcome = ?, updated_at_utc = ? "
            "WHERE social_turn_id = ? AND character_id = ? AND status = 'selected'",
            (status, outcome, utc_text(now), turn_id, character_id),
        )
