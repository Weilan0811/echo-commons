import json
from collections import Counter
from collections.abc import Iterator

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
    def list(self, connection, community_id, conversation_id) -> Iterator[SocialTurn]:
        for row in connection.execute(
            "SELECT social_turn_id FROM social_turns WHERE community_id=? AND conversation_id=? "
            "ORDER BY created_at_utc DESC,social_turn_id DESC",
            (community_id, conversation_id),
        ):
            yield self.get(connection, community_id, row[0])

    def source_messages(self, connection, turn_id) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in connection.execute(
                "SELECT m.message_id FROM social_turn_batches b JOIN input_batch_messages m "
                "USING(input_batch_id) JOIN messages v USING(message_id) "
                "JOIN social_turns s USING(social_turn_id) "
                "WHERE b.social_turn_id=? AND v.sequence<=s.observation_max_sequence "
                "ORDER BY v.sequence",
                (turn_id,),
            )
        )

    def running(self, connection, conversation_id) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM social_turns WHERE conversation_id=? AND status='running'",
                (conversation_id,),
            ).fetchone()
            is not None
        )

    def add(self, connection, turn: SocialTurn, batch_ids: tuple[str, ...]) -> None:
        connection.execute(
            "INSERT INTO social_turns (social_turn_id,community_id,conversation_id,audience_json,"
            "visibility,observation_max_sequence,membership_version,status,completion_json,"
            "created_at_utc,completed_at_utc,chain_id,policy_version,stop_reason,initiation_id) "
            "VALUES (?,?,?,?,?,?,?,?,NULL,?,NULL,?,?,?,?)",
            (
                turn.social_turn_id,
                turn.community_id,
                turn.conversation_id,
                json.dumps(turn.audience, separators=(",", ":")),
                turn.visibility,
                turn.observation_max_sequence,
                turn.membership_version,
                turn.status.value,
                utc_text(turn.created_at_utc),
                turn.chain_id,
                turn.policy_version,
                turn.stop_reason,
                turn.initiation_id,
            ),
        )
        self.link_sources(connection, turn.social_turn_id, batch_ids)

    def link_sources(self, connection, turn_id, batch_ids) -> None:
        connection.executemany(
            "INSERT INTO social_turn_batches VALUES (?,?,?)",
            [(turn_id, batch, i) for i, batch in enumerate(batch_ids)],
        )

    def get(self, connection, community_id, turn_id) -> SocialTurn:
        row = connection.execute(
            "SELECT * FROM social_turns WHERE community_id=? AND social_turn_id=?",
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
            row["policy_version"],
            row["stop_reason"],
            row["initiation_id"],
        )

    def by_id(self, connection, turn_id) -> SocialTurn:
        row = connection.execute(
            "SELECT community_id FROM social_turns WHERE social_turn_id=?", (turn_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("Social turn does not exist")
        return self.get(connection, row[0], turn_id)

    def decision(self, connection, decision: ParticipationDecision) -> None:
        connection.execute(
            "INSERT INTO participation_decisions VALUES (?,?,?,?,?,?,?)",
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

    def decisions(self, connection, turn_id) -> tuple[ParticipationDecision, ...]:
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
                "SELECT * FROM participation_decisions WHERE social_turn_id=? "
                "ORDER BY selection_order,character_id",
                (turn_id,),
            )
        )

    def complete_participation(self, connection, turn_id, character_id, status, outcome, now):
        return (
            connection.execute(
                "UPDATE participation_decisions SET status=?,outcome=?,updated_at_utc=? "
                "WHERE social_turn_id=? AND character_id=? AND status='selected'",
                (status, outcome, utc_text(now), turn_id, character_id),
            ).rowcount
            == 1
        )

    def finish(self, connection, turn_id, summary, now) -> None:
        connection.execute(
            "UPDATE social_turns SET status='completed',completed_at_utc=?,completion_json=? "
            "WHERE social_turn_id=? AND status IN ('pending','running')",
            (utc_text(now), json.dumps(summary, separators=(",", ":")), turn_id),
        )

    def chain(self, connection, chain_id) -> SocialChain:
        row = connection.execute(
            "SELECT * FROM social_chains WHERE chain_id=?", (chain_id,)
        ).fetchone()
        if row is None:
            raise NotFoundError("Social round does not exist")
        return SocialChain(
            row["chain_id"],
            row["community_id"],
            row["conversation_id"],
            row["max_messages"],
            row["max_tasks"],
            row["message_count"],
            row["task_count"],
            row["status"],
            row["stop_reason"],
            utc_datetime(row["created_at_utc"]),
            utc_datetime(row["completed_at_utc"]) if row["completed_at_utc"] else None,
        )

    def active_chain(self, connection, conversation_id) -> SocialChain | None:
        row = connection.execute(
            "SELECT chain_id FROM social_chains WHERE conversation_id=? AND status='active'",
            (conversation_id,),
        ).fetchone()
        return self.chain(connection, row[0]) if row else None

    def add_chain(self, connection, chain: SocialChain) -> None:
        connection.execute(
            "INSERT INTO social_chains VALUES (?,?,?,?,?,?,?,?,?,?,?)",
            (
                chain.chain_id,
                chain.community_id,
                chain.conversation_id,
                chain.max_messages,
                chain.max_tasks,
                chain.message_count,
                chain.task_count,
                chain.status,
                chain.stop_reason,
                utc_text(chain.created_at_utc),
                None,
            ),
        )

    def attach_batch(self, connection, chain_id, batch_id) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO social_chain_batches VALUES (?,?)", (chain_id, batch_id)
        )

    def attach_message(self, connection, chain_id, message_id) -> None:
        connection.execute(
            "INSERT OR IGNORE INTO social_chain_batches SELECT ?,input_batch_id "
            "FROM input_batch_messages WHERE message_id=?",
            (chain_id, message_id),
        )

    def round_messages(self, connection, chain_id) -> tuple[str, ...]:
        return tuple(
            row[0]
            for row in connection.execute(
                "SELECT m.message_id FROM social_chain_batches b JOIN input_batch_messages m "
                "USING(input_batch_id) JOIN messages v USING(message_id) WHERE b.chain_id=? "
                "ORDER BY v.sequence",
                (chain_id,),
            )
        )

    def considered(self, connection, chain_id, membership_id) -> int:
        row = connection.execute(
            "SELECT considered_through_sequence FROM social_observations "
            "WHERE chain_id=? AND membership_id=?",
            (chain_id, membership_id),
        ).fetchone()
        return row[0] if row else 0

    def observe(self, connection, chain_id, membership_id, sequence) -> None:
        connection.execute(
            "INSERT INTO social_observations VALUES (?,?,?) "
            "ON CONFLICT(chain_id,membership_id) DO UPDATE SET considered_through_sequence="
            "MAX(considered_through_sequence,excluded.considered_through_sequence)",
            (chain_id, membership_id, sequence),
        )

    def stop_chain(self, connection, chain_id, reason, at, *, cancelled=False) -> None:
        connection.execute(
            "UPDATE social_chains SET status=?,stop_reason=?,completed_at_utc=? "
            "WHERE chain_id=? AND status='active'",
            ("cancelled" if cancelled else "completed", reason, utc_text(at), chain_id),
        )

    def task_created(self, connection, chain_id) -> None:
        connection.execute(
            "UPDATE social_chains SET task_count=task_count+1 WHERE chain_id=?", (chain_id,)
        )

    def message_created(self, connection, chain_id) -> None:
        connection.execute(
            "UPDATE social_chains SET message_count=message_count+1 WHERE chain_id=?", (chain_id,)
        )

    def attempts(self, connection, chain_id, character_id) -> int:
        return connection.execute(
            "SELECT COUNT(*) FROM participation_decisions p "
            "JOIN social_turns s USING(social_turn_id) "
            "WHERE s.chain_id=? AND p.character_id=? AND p.selection_order IS NOT NULL",
            (chain_id, character_id),
        ).fetchone()[0]

    def awaiting_expression(self, connection, chain_id) -> bool:
        return (
            connection.execute(
                "SELECT 1 FROM participation_decisions p JOIN social_turns s USING(social_turn_id) "
                "WHERE s.chain_id=? AND p.outcome='pending_expression' LIMIT 1",
                (chain_id,),
            ).fetchone()
            is not None
        )

    def available_message_slots(self, connection, chain):
        pending = connection.execute(
            "SELECT COUNT(*) FROM participation_decisions p JOIN social_turns s "
            "USING(social_turn_id) "
            "WHERE s.chain_id=? AND p.outcome='pending_expression'",
            (chain.chain_id,),
        ).fetchone()[0]
        return max(0, chain.max_messages - chain.message_count - pending)

    def cancel_turn(self, connection, turn_id, reason, at) -> None:
        for item in self.decisions(connection, turn_id):
            if item.status is ParticipationStatus.SELECTED:
                self.complete_participation(
                    connection, turn_id, item.character_id, "cancelled", "cancelled", at
                )
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
