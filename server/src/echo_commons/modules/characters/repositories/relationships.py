from __future__ import annotations

import json
import sqlite3
from datetime import datetime
from uuid import UUID

from echo_commons.infrastructure.database.mapping import utc_datetime, utc_text
from echo_commons.modules.characters.domain.relationship import (
    RelationshipEvidence,
    RelationshipEvidenceKind,
    RelationshipKey,
    RelationshipState,
    RelationshipValues,
)


class RelationshipRepository:
    def keys(
        self, connection: sqlite3.Connection, community_id: str, character_id: str
    ) -> tuple[RelationshipKey, ...]:
        return tuple(
            RelationshipKey(community_id, character_id, row[0], row[1])
            for row in connection.execute(
                "SELECT target_kind, target_id FROM relationship_state WHERE "
                "community_id = ? AND observer_character_id = ? ORDER BY target_kind, "
                "target_id",
                (community_id, character_id),
            )
        )

    def get(
        self, connection: sqlite3.Connection, key: RelationshipKey, at: datetime
    ) -> RelationshipState:
        row = connection.execute(
            "SELECT * FROM relationship_state WHERE community_id = ? AND "
            "observer_character_id = ? AND target_kind = ? AND target_id = ?",
            (key.community_id, key.observer_character_id, key.target_kind.value, key.target_id),
        ).fetchone()
        if row is None:
            return RelationshipState.stranger(key, updated_at_utc=at)
        values = (
            None
            if row["affection"] is None
            else RelationshipValues(row["affection"], row["trust"], row["attachment"])
        )
        return RelationshipState(
            key,
            row["relationship_type"],
            values,
            row["state_version"],
            utc_datetime(row["updated_at_utc"]),
            UUID(row["friend_qualifying_evidence_id"])
            if row["friend_qualifying_evidence_id"]
            else None,
            row["attitude_summary"],
            tuple(UUID(item) for item in json.loads(row["attitude_source_refs_json"])),
        )

    def evidence(
        self,
        connection: sqlite3.Connection,
        key: RelationshipKey,
        source_kind: str,
        source_ref: str,
    ) -> RelationshipEvidence | None:
        row = connection.execute(
            "SELECT * FROM relation_evidence WHERE community_id = ? AND "
            "observer_character_id = ? AND target_kind = ? AND target_id = ? AND "
            "source_kind = ? AND source_ref = ?",
            (
                key.community_id,
                key.observer_character_id,
                key.target_kind.value,
                key.target_id,
                source_kind,
                source_ref,
            ),
        ).fetchone()
        if row is None:
            return None
        return RelationshipEvidence(
            UUID(row["evidence_id"]),
            key,
            RelationshipEvidenceKind(row["evidence_kind"]),
            source_kind,
            source_ref,
            utc_datetime(row["occurred_at_utc"]),
            utc_datetime(row["recorded_at_utc"]),
        )

    def add_evidence(self, connection: sqlite3.Connection, evidence: RelationshipEvidence) -> None:
        key = evidence.key
        connection.execute(
            "INSERT INTO relation_evidence VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)",
            (
                str(evidence.evidence_id),
                key.community_id,
                key.observer_character_id,
                key.target_kind.value,
                key.target_id,
                evidence.evidence_kind.value,
                evidence.source_kind,
                evidence.source_ref,
                utc_text(evidence.occurred_at_utc),
                utc_text(evidence.recorded_at_utc),
            ),
        )

    def save(self, connection: sqlite3.Connection, state: RelationshipState) -> None:
        key, values = state.key, state.values
        connection.execute(
            "INSERT INTO relationship_state VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?) "
            "ON CONFLICT(community_id, observer_character_id, target_kind, target_id) "
            "DO UPDATE SET "
            "relationship_type = excluded.relationship_type, affection = "
            "excluded.affection, trust = excluded.trust, attachment = "
            "excluded.attachment, "
            "friend_qualifying_evidence_id = excluded.friend_qualifying_evidence_id, "
            "attitude_summary = excluded.attitude_summary, "
            "attitude_source_refs_json = excluded.attitude_source_refs_json, "
            "state_version = excluded.state_version, updated_at_utc = "
            "excluded.updated_at_utc",
            (
                key.community_id,
                key.observer_character_id,
                key.target_kind.value,
                key.target_id,
                state.relationship_type.value,
                values.affection if values else None,
                values.trust if values else None,
                values.attachment if values else None,
                str(state.friend_qualifying_evidence_id)
                if state.friend_qualifying_evidence_id
                else None,
                state.attitude_summary,
                json.dumps([str(ref) for ref in state.attitude_source_refs]),
                state.state_version,
                utc_text(state.updated_at_utc),
            ),
        )
