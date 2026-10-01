"""Persistence for character self-state entries and directed relationships."""

from __future__ import annotations

import json
from datetime import datetime
from uuid import UUID

import aiosqlite

from echo_server.domain.character_state_entry import CharacterStateEntry
from echo_server.domain.errors import DomainInvariantError, require_non_empty, require_sequence
from echo_server.domain.relationship import (
    RelationshipEvidence,
    RelationshipKey,
    RelationshipState,
    RelationshipType,
    RelationshipValues,
)
from echo_server.store.database import Database
from echo_server.store.repository_support import (
    as_json,
    get_connection,
    parse_time,
    require_write_connection,
    utc_text,
)


def _required_uuid(value: object, field_name: str) -> UUID:
    if not isinstance(value, str):
        raise DomainInvariantError(f"{field_name} must contain a UUID")
    try:
        return UUID(value)
    except ValueError as exc:
        raise DomainInvariantError(f"{field_name} must contain a UUID") from exc


def _required_time(value: object, field_name: str) -> datetime:
    parsed = parse_time(value if isinstance(value, str) else None)
    if parsed is None:
        raise DomainInvariantError(f"{field_name} must contain a timestamp")
    return parsed


def _optional_time(value: object, field_name: str) -> datetime | None:
    if value is None:
        return None
    return _required_time(value, field_name)


def _check_rowcount(rowcount: int, entity: str) -> None:
    if rowcount != 1:
        raise RuntimeError(f"{entity} persistence precondition failed")


def _character_state_from_row(row: aiosqlite.Row) -> CharacterStateEntry:
    return CharacterStateEntry(
        entry_id=_required_uuid(row["entry_id"], "entry_id"),
        character_id=row["character_id"],
        state_kind=row["state_kind"],
        value=row["value"],
        source_kind=row["source_kind"],
        source_ref=row["source_ref"],
        state_version=int(row["state_version"]),
        recorded_at_utc=_required_time(row["recorded_at_utc"], "recorded_at_utc"),
        expires_at_utc=_optional_time(row["expires_at_utc"], "expires_at_utc"),
    )


def _relationship_key_from_row(row: aiosqlite.Row) -> RelationshipKey:
    return RelationshipKey(
        account_id=row["account_id"],
        observer_character_id=row["observer_character_id"],
        target_kind=row["target_kind"],
        target_id=row["target_id"],
    )


def _relationship_evidence_from_row(row: aiosqlite.Row) -> RelationshipEvidence:
    return RelationshipEvidence(
        evidence_id=_required_uuid(row["evidence_id"], "evidence_id"),
        key=_relationship_key_from_row(row),
        evidence_kind=row["evidence_kind"],
        source_kind=row["source_kind"],
        source_ref=row["source_ref"],
        occurred_at_utc=_required_time(row["occurred_at_utc"], "occurred_at_utc"),
        recorded_at_utc=_required_time(row["recorded_at_utc"], "recorded_at_utc"),
    )


def _relationship_state_from_row(row: aiosqlite.Row) -> RelationshipState:
    relationship_type = RelationshipType(row["relationship_type"])
    if relationship_type is RelationshipType.STRANGER:
        values = None
    else:
        values = RelationshipValues(
            affection=float(row["affection"]),
            trust=float(row["trust"]),
            attachment=float(row["attachment"]),
        )
    refs = json.loads(row["attitude_source_refs_json"])
    if not isinstance(refs, list):
        raise DomainInvariantError("attitude_source_refs_json must contain a JSON array")
    return RelationshipState(
        key=_relationship_key_from_row(row),
        relationship_type=relationship_type,
        values=values,
        state_version=int(row["state_version"]),
        updated_at_utc=_required_time(row["updated_at_utc"], "updated_at_utc"),
        friend_qualifying_evidence_id=(
            _required_uuid(row["friend_qualifying_evidence_id"], "friend_qualifying_evidence_id")
            if row["friend_qualifying_evidence_id"] is not None
            else None
        ),
        attitude_summary=row["attitude_summary"],
        attitude_source_refs=tuple(_required_uuid(ref, "attitude_source_ref") for ref in refs),
    )


class CharacterStateEntryRepository:
    """Append-only state history with a compare-and-set version per category."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def list_latest_for_character(
        self,
        character_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[CharacterStateEntry, ...]:
        """Return the newest entry for each category, including expired entries."""

        character = require_non_empty(character_id, "character_id")
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            """SELECT entry.* FROM character_state_entries AS entry
            WHERE entry.character_id = ? AND entry.state_version = (
                SELECT MAX(latest.state_version) FROM character_state_entries AS latest
                WHERE latest.character_id = entry.character_id
                    AND latest.state_kind = entry.state_kind
            ) ORDER BY entry.state_kind""",
            (character,),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(_character_state_from_row(row) for row in rows)

    async def append(
        self,
        entry: CharacterStateEntry,
        *,
        expected_version: int,
        connection: aiosqlite.Connection | None = None,
    ) -> CharacterStateEntry:
        """Append the next version for one category within a caller transaction."""

        conn = require_write_connection(connection)
        expected = require_sequence(expected_version, "expected_version", minimum=0)
        if entry.state_version != expected + 1:
            raise DomainInvariantError("character state entry must be the next category version")
        cursor = await conn.execute(
            """INSERT INTO character_state_entries(
                entry_id, character_id, state_kind, value, source_kind, source_ref,
                state_version, recorded_at_utc, expires_at_utc
            ) SELECT ?, ?, ?, ?, ?, ?, ?, ?, ?
            WHERE COALESCE((
                SELECT MAX(state_version) FROM character_state_entries
                WHERE character_id = ? AND state_kind = ?
            ), 0) = ?""",
            (
                str(entry.entry_id),
                entry.character_id,
                entry.state_kind.value,
                entry.value,
                entry.source_kind,
                entry.source_ref,
                entry.state_version,
                utc_text(entry.recorded_at_utc),
                utc_text(entry.expires_at_utc) if entry.expires_at_utc else None,
                entry.character_id,
                entry.state_kind.value,
                expected,
            ),
        )
        _check_rowcount(cursor.rowcount, "character state entry")
        return entry


class RelationshipEvidenceRepository:
    """Append-only, source-deduplicated evidence for one directed relationship."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(
        self,
        evidence_id: UUID,
        connection: aiosqlite.Connection | None = None,
    ) -> RelationshipEvidence | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            "SELECT * FROM relation_evidence WHERE evidence_id = ?",
            (str(evidence_id),),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return _relationship_evidence_from_row(row) if row else None

    async def append(
        self,
        evidence: RelationshipEvidence,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> RelationshipEvidence:
        """Record an objective source event without replacing prior evidence."""

        conn = require_write_connection(connection)
        await conn.execute(
            """INSERT INTO relation_evidence(
                evidence_id, account_id, observer_character_id, target_kind, target_id,
                evidence_kind, source_kind, source_ref, occurred_at_utc, recorded_at_utc
            ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?)""",
            (
                str(evidence.evidence_id),
                evidence.key.account_id,
                evidence.key.observer_character_id,
                evidence.key.target_kind.value,
                evidence.key.target_id,
                evidence.evidence_kind.value,
                evidence.source_kind,
                evidence.source_ref,
                utc_text(evidence.occurred_at_utc),
                utc_text(evidence.recorded_at_utc),
            ),
        )
        return evidence

    async def ensure(
        self,
        evidence: RelationshipEvidence,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> RelationshipEvidence:
        """Append one evidence row idempotently by its deterministic ID."""

        existing = await self.get(evidence.evidence_id, connection=connection)
        if existing is None:
            return await self.append(evidence, connection=connection)
        if existing != evidence:
            raise DomainInvariantError(
                "relationship evidence identity already contains different data"
            )
        return existing


class RelationshipStateRepository:
    """Read and compare-and-set persistence for directed relationship state."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(
        self,
        key: RelationshipKey,
        connection: aiosqlite.Connection | None = None,
    ) -> RelationshipState | None:
        conn = get_connection(self.database, connection)
        cursor = await conn.execute(
            """SELECT * FROM relationship_state WHERE account_id = ?
                AND observer_character_id = ? AND target_kind = ? AND target_id = ?""",
            (
                key.account_id,
                key.observer_character_id,
                key.target_kind.value,
                key.target_id,
            ),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        return _relationship_state_from_row(row) if row else None

    async def save(
        self,
        state: RelationshipState,
        *,
        expected_version: int,
        connection: aiosqlite.Connection | None = None,
    ) -> RelationshipState:
        """Persist exactly one changed version in the caller's transaction."""

        conn = require_write_connection(connection)
        expected = require_sequence(expected_version, "expected_version", minimum=0)
        if state.state_version != expected + 1:
            raise DomainInvariantError("relationship state must be the next version")
        values = state.values
        relation_values = (
            state.relationship_type.value,
            values.affection if values is not None else None,
            values.trust if values is not None else None,
            values.attachment if values is not None else None,
            (
                str(state.friend_qualifying_evidence_id)
                if state.friend_qualifying_evidence_id is not None
                else None
            ),
            state.attitude_summary,
            as_json([str(ref) for ref in state.attitude_source_refs]),
            state.state_version,
            utc_text(state.updated_at_utc),
        )
        relation_key = (
            state.key.account_id,
            state.key.observer_character_id,
            state.key.target_kind.value,
            state.key.target_id,
        )
        if expected == 0:
            cursor = await conn.execute(
                """INSERT INTO relationship_state(
                    account_id, observer_character_id, target_kind, target_id,
                    relationship_type, affection, trust, attachment,
                    friend_qualifying_evidence_id, attitude_summary, attitude_source_refs_json,
                    state_version, updated_at_utc
                ) VALUES (?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?, ?)
                ON CONFLICT(account_id, observer_character_id, target_kind, target_id)
                DO UPDATE SET
                    relationship_type = excluded.relationship_type,
                    affection = excluded.affection,
                    trust = excluded.trust,
                    attachment = excluded.attachment,
                    friend_qualifying_evidence_id = excluded.friend_qualifying_evidence_id,
                    attitude_summary = excluded.attitude_summary,
                    attitude_source_refs_json = excluded.attitude_source_refs_json,
                    state_version = excluded.state_version,
                    updated_at_utc = excluded.updated_at_utc
                WHERE relationship_state.state_version = 0""",
                (*relation_key, *relation_values),
            )
        else:
            cursor = await conn.execute(
                """UPDATE relationship_state SET
                    relationship_type = ?, affection = ?, trust = ?, attachment = ?,
                    friend_qualifying_evidence_id = ?, attitude_summary = ?,
                    attitude_source_refs_json = ?, state_version = ?, updated_at_utc = ?
                WHERE account_id = ? AND observer_character_id = ?
                    AND target_kind = ? AND target_id = ? AND state_version = ?""",
                (*relation_values, *relation_key, expected),
            )
        _check_rowcount(cursor.rowcount, "relationship state")
        return state


__all__ = [
    "CharacterStateEntryRepository",
    "RelationshipEvidenceRepository",
    "RelationshipStateRepository",
]
