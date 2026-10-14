from __future__ import annotations

import sqlite3
from datetime import datetime

from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.modules.memory.repositories.provenance import MemoryProvenanceRepository


class LongTermMemoryRepository:
    def active_rows(
        self,
        connection: sqlite3.Connection,
        community_id: str,
        character_id: str,
        *,
        recorded_before: datetime,
    ) -> tuple[sqlite3.Row, ...]:
        rows = []
        for kind, table, occurred in (
            ("fact", "memory_facts", "occurred_at_utc"),
            ("cognition", "memory_cognitions", "formed_at_utc"),
        ):
            rows.extend(
                dict(row)
                | {
                    "record_kind": kind,
                    "content_version": str(row["version"]),
                    "occurred_at_utc": row[occurred],
                }
                for row in connection.execute(
                    f"SELECT * FROM {table} WHERE community_id=? AND character_id=? "
                    "AND status='current' AND recorded_at_utc<=?",
                    (community_id, character_id, utc_text(recorded_before)),
                )
            )
        valid = []
        for row in rows:
            sources = MemoryProvenanceRepository().record_sources(
                connection,
                community_id,
                character_id,
                row["record_kind"],
                row["memory_id"],
                row["version"],
            )
            if sources and all(item["readable"] for item in sources):
                valid.append(row)
        return tuple(
            sorted(
                valid, key=lambda row: (-row["salience"], row["recorded_at_utc"], row["memory_id"])
            )
        )

    def review_rows(self, connection, community, character, recorded_before):
        return tuple(
            dict(row)
            | {
                "record_kind": "cognition",
                "content_version": str(row["version"]),
            }
            for row in connection.execute(
                "SELECT * FROM memory_cognitions WHERE community_id=? AND character_id=? "
                "AND status='needs_review' AND recorded_at_utc<=? ORDER BY recorded_at_utc LIMIT 8",
                (community, character, utc_text(recorded_before)),
            )
        )

    def get(self, connection, community, character, reference):
        table = {"fact": "memory_facts", "cognition": "memory_cognitions"}[reference.record_kind]
        row = connection.execute(
            f"SELECT * FROM {table} WHERE community_id=? AND character_id=? "
            "AND memory_id=? AND version=?",
            (community, character, reference.memory_id, reference.version),
        ).fetchone()
        if row is None:
            from echo_commons.shared.errors import NotFoundError

            raise NotFoundError("Long-term record is unavailable in this character scope")
        return row
