from __future__ import annotations

import json
import sqlite3
from collections import Counter
from collections.abc import Iterator
from datetime import datetime

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.social.domain import (
    ParticipationDecision,
    ParticipationStatus,
    SocialChain,
    SocialTurn,
    TurnStatus,
)
from echo_commons.shared.errors import NotFoundError


class SocialRepository:
    def list(
        self, connection: sqlite3.Connection, community_id: str, conversation_id: str
    ) -> Iterator[SocialTurn]:
        for row in connection.execute(
            "SELECT social_turn_id FROM social_turns WHERE community_id = ? "
            "AND conversation_id = ? ORDER BY created_at_utc DESC, social_turn_id DESC",
            (community_id, conversation_id),
        ):
            yield self.get(connection, community_id, row[0])

    def source_messages(self, connection: sqlite3.Connection, turn_id: str) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in connection.execute(
                "SELECT m.message_id FROM social_turn_batches b JOIN input_batch_messages m "
                "ON m.input_batch_id = b.input_batch_id WHERE b.social_turn_id = ? "
                "ORDER BY b.ordinal, m.message_id",
                (turn_id,),
            )
        )

    def running(self, connection: sqlite3.Connection, conversation_id: str) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM social_turns WHERE conversation_id = ? AND status = 'running'",
                (conversation_id,),
            ).fetchone()
            is not None
        )

    def root_messages(self, connection: sqlite3.Connection, turn_id: str) -> tuple[str, ...]:
        turn = self.by_id(connection, turn_id)
        if turn.initiation_id is None:
            return self.source_messages(connection, turn_id)
        return tuple(
            row[0]
            for row in connection.execute(
                "SELECT message_id FROM messages WHERE source_turn_id=? ORDER BY sequence",
                (turn_id,),
            )
        )

    def add(
        self, connection: sqlite3.Connection, turn: SocialTurn, batch_ids: tuple[str, ...]
    ) -> None:
        connection.execute(
            "INSERT INTO social_turns (social_turn_id,community_id,conversation_id,audience_json,"
            "visibility,observation_max_sequence,membership_version,status,completion_json,"
            "created_at_utc,completed_at_utc,chain_id,parent_turn_id,depth,"
            "policy_version,stop_reason,initiation_id) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
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
                turn.chain_id,
                turn.parent_turn_id,
                turn.depth,
                turn.policy_version,
                turn.stop_reason,
                turn.initiation_id,
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
            row["chain_id"],
            row["parent_turn_id"],
            row["depth"],
            row["policy_version"],
            row["stop_reason"],
            row["initiation_id"],
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
            "completion_json = ? WHERE social_turn_id = ? AND status IN ('pending','running')",
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
    ) -> bool:
        return (
            connection.execute(
                "UPDATE participation_decisions SET status = ?, outcome = ?, updated_at_utc = ? "
                "WHERE social_turn_id = ? AND character_id = ? AND status = 'selected'",
                (status, outcome, utc_text(now), turn_id, character_id),
            ).rowcount
            == 1
        )

    def chain(self, connection: sqlite3.Connection, chain_id: str) -> SocialChain:
        row = connection.execute(
            "SELECT * FROM social_chains WHERE chain_id=?", (chain_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("Social chain does not exist")
        return SocialChain(
            row["chain_id"],
            row["community_id"],
            row["conversation_id"],
            row["root_turn_id"],
            row["max_messages"],
            row["max_tasks"],
            row["message_count"],
            row["task_count"],
            row["status"],
            row["stop_reason"],
            utc_datetime(row["created_at_utc"]),
            utc_datetime(row["completed_at_utc"]) if row["completed_at_utc"] else None,
        )

    def by_id(self, connection: sqlite3.Connection, turn_id: str) -> SocialTurn:
        row = connection.execute(
            "SELECT community_id FROM social_turns WHERE social_turn_id=?",
            (turn_id,),
        ).fetchone()
        if row is None:
            raise NotFoundError("Social turn does not exist")
        return self.get(connection, row[0], turn_id)

    def add_chain(self, connection: sqlite3.Connection, chain: SocialChain) -> None:
        connection.execute(
            "INSERT INTO social_chains (chain_id,community_id,conversation_id,root_turn_id,"
            "max_messages,max_tasks,status,created_at_utc) VALUES (?,?,?,?,?,?,?,?)",
            (
                chain.chain_id,
                chain.community_id,
                chain.conversation_id,
                chain.root_turn_id,
                chain.max_messages,
                chain.max_tasks,
                chain.status,
                utc_text(chain.created_at_utc),
            ),
        )

    def stop_chain(
        self,
        connection: sqlite3.Connection,
        chain_id: str,
        reason: str,
        at: datetime,
        *,
        cancelled: bool = False,
    ) -> None:
        connection.execute(
            "UPDATE social_chains SET status=?,stop_reason=?,completed_at_utc=? "
            "WHERE chain_id=? AND status='active'",
            ("cancelled" if cancelled else "completed", reason, utc_text(at), chain_id),
        )
        connection.execute(
            "UPDATE social_triggers SET status='discarded',reason_code=? "
            "WHERE chain_id=? AND status='pending'",
            (reason, chain_id),
        )

    def candidate(
        self,
        connection: sqlite3.Connection,
        turn_id: str,
        character_id: str,
        membership_id: str,
        reason: str | None,
        at: datetime,
    ) -> None:
        connection.execute(
            "INSERT INTO social_candidates VALUES (?,?,?,?,?)",
            (turn_id, character_id, membership_id, "excluded" if reason else "waiting", reason),
        )
        if reason:
            self.decision(
                connection,
                ParticipationDecision(
                    turn_id,
                    character_id,
                    reason,
                    None,
                    ParticipationStatus.SILENT,
                    "silent",
                    at,
                ),
            )

    def waiting(self, connection: sqlite3.Connection, turn_id: str) -> tuple[sqlite3.Row, ...]:
        return tuple(
            connection.execute(
                "SELECT * FROM social_candidates WHERE social_turn_id=? AND status='waiting'",
                (turn_id,),
            )
        )

    def mark_candidate(
        self,
        connection: sqlite3.Connection,
        turn_id: str,
        character_id: str,
        status: str,
        reason: str,
    ) -> None:
        connection.execute(
            "UPDATE social_candidates SET status=?,reason_code=? "
            "WHERE social_turn_id=? AND character_id=? AND status='waiting'",
            (status, reason, turn_id, character_id),
        )

    def close_candidates(
        self,
        connection: sqlite3.Connection,
        turn_id: str,
        reason: str,
        at: datetime,
    ) -> None:
        for candidate in self.waiting(connection, turn_id):
            self.mark_candidate(connection, turn_id, candidate["character_id"], "skipped", reason)
            self.decision(
                connection,
                ParticipationDecision(
                    turn_id,
                    candidate["character_id"],
                    reason,
                    None,
                    ParticipationStatus.SILENT,
                    "silent",
                    at,
                ),
            )

    def set_stop_reason(
        self,
        connection: sqlite3.Connection,
        turn_id: str,
        reason: str,
    ) -> None:
        connection.execute(
            "UPDATE social_turns SET stop_reason=? WHERE social_turn_id=?",
            (reason, turn_id),
        )

    def task_created(self, connection: sqlite3.Connection, chain_id: str) -> None:
        connection.execute(
            "UPDATE social_chains SET task_count=task_count+1 WHERE chain_id=?",
            (chain_id,),
        )

    def message_created(self, connection: sqlite3.Connection, chain_id: str) -> None:
        connection.execute(
            "UPDATE social_chains SET message_count=message_count+1 WHERE chain_id=?",
            (chain_id,),
        )

    def attempts(self, connection: sqlite3.Connection, chain_id: str, character_id: str) -> int:
        return connection.execute(
            "SELECT COUNT(*) FROM participation_decisions p JOIN social_turns t "
            "ON t.social_turn_id=p.social_turn_id WHERE t.chain_id=? AND p.character_id=? "
            "AND p.selection_order IS NOT NULL",
            (chain_id, character_id),
        ).fetchone()[0]

    def trigger(
        self,
        connection: sqlite3.Connection,
        chain_id: str,
        turn_id: str,
        batch_id: str,
        at: datetime,
    ) -> None:
        connection.execute(
            "INSERT INTO social_triggers (input_batch_id,chain_id,origin_turn_id,status,"
            "created_at_utc) VALUES (?,?,?,'pending',?)",
            (batch_id, chain_id, turn_id, utc_text(at)),
        )

    def pending_triggers(self, connection: sqlite3.Connection) -> tuple[sqlite3.Row, ...]:
        return tuple(
            connection.execute(
                "SELECT s.* FROM social_triggers s JOIN social_chains c USING(chain_id) "
                "WHERE s.status='pending' AND c.status='active' ORDER BY s.created_at_utc",
            )
        )

    def consume_trigger(self, connection: sqlite3.Connection, batch_id: str) -> None:
        connection.execute(
            "UPDATE social_triggers SET status='consumed' WHERE input_batch_id=? "
            "AND status='pending'",
            (batch_id,),
        )

    def active_turns(self, connection: sqlite3.Connection) -> tuple[SocialTurn, ...]:
        return tuple(
            self.get(connection, row["community_id"], row["social_turn_id"])
            for row in connection.execute(
                "SELECT community_id,social_turn_id FROM social_turns "
                "WHERE status='running' AND chain_id IS NOT NULL",
            )
        )

    def cancel_turn(
        self,
        connection: sqlite3.Connection,
        turn_id: str,
        reason: str,
        at: datetime,
    ) -> None:
        for item in self.decisions(connection, turn_id):
            if item.status is ParticipationStatus.SELECTED:
                self.complete_participation(
                    connection,
                    turn_id,
                    item.character_id,
                    "cancelled",
                    "cancelled",
                    at,
                )
        self.close_candidates(connection, turn_id, reason, at)
        connection.execute(
            "UPDATE social_turns SET status='cancelled',completed_at_utc=?,completion_json=?,"
            "stop_reason=? WHERE social_turn_id=? AND status IN ('pending','running')",
            (
                utc_text(at),
                json.dumps(
                    dict(Counter(item.outcome for item in self.decisions(connection, turn_id)))
                ),
                reason,
                turn_id,
            ),
        )
