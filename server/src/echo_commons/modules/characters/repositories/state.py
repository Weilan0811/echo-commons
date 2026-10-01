from __future__ import annotations

import sqlite3
from datetime import datetime

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.characters.domain.state import StateEntry, StateKind


class StateRepository:
    def latest(
        self, connection: sqlite3.Connection, character_id: str, kind: StateKind, at: datetime
    ) -> StateEntry | None:
        row = connection.execute(
            "SELECT * FROM character_state_entries WHERE character_id = ? AND state_kind = ? "
            "AND recorded_at_utc <= ? ORDER BY state_version DESC LIMIT 1",
            (character_id, kind.value, utc_text(at)),
        ).fetchone()
        if row is None:
            return None
        entry = self.from_row(row)
        return entry if entry.effective(at) else None

    def from_row(self, row: sqlite3.Row) -> StateEntry:
        return StateEntry(
            row["entry_id"],
            row["community_id"],
            row["character_id"],
            StateKind(row["state_kind"]),
            row["value"],
            row["source_kind"],
            row["source_ref"],
            row["state_version"],
            utc_datetime(row["recorded_at_utc"]),
            utc_datetime(row["expires_at_utc"]) if row["expires_at_utc"] else None,
        )

    def add(self, connection: sqlite3.Connection, entry: StateEntry) -> None:
        connection.execute(
            "INSERT INTO character_state_entries VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                entry.entry_id,
                entry.community_id,
                entry.character_id,
                entry.state_kind.value,
                entry.value,
                entry.source_kind,
                entry.source_ref,
                entry.state_version,
                utc_text(entry.recorded_at_utc),
                utc_text(entry.expires_at_utc) if entry.expires_at_utc else None,
            ),
        )
