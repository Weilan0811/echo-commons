"""Persistence for bounded operational trace events and their delivery queue."""

from __future__ import annotations

import json
from dataclasses import dataclass, replace
from datetime import datetime, timedelta
from typing import Any
from uuid import UUID

import aiosqlite

from echo_server.store.database import Database
from echo_server.store.repository_support import (
    as_json,
    parse_time,
    require_write_connection,
    utc_text,
)


@dataclass(frozen=True, slots=True)
class TraceOutboxEntry:
    """One claimed operational Trace waiting for materialization."""

    trace_id: UUID
    correlation_id: UUID
    kind: str
    entity_type: str
    entity_id: str
    payload_json: str
    created_at_utc: datetime
    status: str
    attempt_count: int
    available_at_utc: datetime
    lease_owner: str | None
    lease_until_utc: datetime | None
    last_error_code: str | None


@dataclass(frozen=True, slots=True)
class TraceRecord:
    """One materialized operational Trace event."""

    trace_id: UUID
    correlation_id: UUID
    kind: str
    entity_type: str
    entity_id: str
    payload: dict[str, Any]
    created_at_utc: datetime


class TraceRepository:
    """Transactional outbox and durable materialization boundary for Traces."""

    def __init__(self, database: Database) -> None:
        self.database = database

    async def enqueue(
        self,
        *,
        trace_id: UUID,
        correlation_id: UUID,
        kind: str,
        entity_type: str,
        entity_id: str,
        payload: dict[str, Any],
        created_at: datetime,
        connection: aiosqlite.Connection | None = None,
    ) -> None:
        """Persist one event in the outbox using the caller's transaction."""

        conn = require_write_connection(connection)
        created_at_text = utc_text(created_at)
        cursor = await conn.execute(
            "INSERT INTO trace_outbox(trace_id, correlation_id, kind, entity_type, entity_id, "
            "payload_json, created_at_utc, status, attempt_count, available_at_utc) "
            "VALUES (?, ?, ?, ?, ?, ?, ?, 'pending', 0, ?) "
            "ON CONFLICT(trace_id) DO NOTHING",
            (
                str(trace_id),
                str(correlation_id),
                kind,
                entity_type,
                entity_id,
                as_json(payload),
                created_at_text,
                created_at_text,
            ),
        )
        await cursor.close()

    async def recover_expired(
        self,
        now_utc: datetime,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> int:
        """Return expired claimed events to the pending queue."""

        if connection is None:
            async with self.database.transaction(immediate=True) as conn:
                return await self.recover_expired(now_utc, connection=conn)
        conn = require_write_connection(connection)
        now = utc_text(now_utc)
        cursor = await conn.execute(
            "UPDATE trace_outbox SET status = 'pending', lease_owner = NULL, "
            "lease_until_utc = NULL, available_at_utc = ? "
            "WHERE status = 'processing' AND lease_until_utc <= ?",
            (now, now),
        )
        try:
            return cursor.rowcount
        finally:
            await cursor.close()

    async def claim_next(
        self,
        *,
        worker_id: str,
        now_utc: datetime,
        lease_seconds: float,
        connection: aiosqlite.Connection | None = None,
    ) -> TraceOutboxEntry | None:
        """Claim one due event with a durable lease."""

        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        if lease_seconds <= 0:
            raise ValueError("lease_seconds must be positive")
        if connection is None:
            async with self.database.transaction(immediate=True) as conn:
                return await self.claim_next(
                    worker_id=worker_id,
                    now_utc=now_utc,
                    lease_seconds=lease_seconds,
                    connection=conn,
                )

        conn = require_write_connection(connection)
        now = _require_time(now_utc, "now_utc")
        await self.recover_expired(now, connection=conn)
        cursor = await conn.execute(
            "SELECT * FROM trace_outbox WHERE status = 'pending' "
            "AND available_at_utc <= ? "
            "ORDER BY available_at_utc, created_at_utc, trace_id LIMIT 1",
            (utc_text(now),),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        if row is None:
            return None

        lease_until = now + timedelta(seconds=lease_seconds)
        cursor = await conn.execute(
            "UPDATE trace_outbox SET status = 'processing', lease_owner = ?, "
            "lease_until_utc = ?, attempt_count = attempt_count + 1 "
            "WHERE trace_id = ? AND status = 'pending'",
            (worker_id, utc_text(lease_until), row["trace_id"]),
        )
        try:
            if cursor.rowcount != 1:
                return None
        finally:
            await cursor.close()
        return replace(
            _to_entry(row),
            status="processing",
            attempt_count=int(row["attempt_count"]) + 1,
            lease_owner=worker_id,
            lease_until_utc=lease_until,
        )

    async def materialize(
        self,
        trace_id: UUID,
        *,
        worker_id: str,
        connection: aiosqlite.Connection | None = None,
    ) -> bool:
        """Move one owned event into ``traces`` exactly once."""

        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        if connection is None:
            async with self.database.transaction(immediate=True) as conn:
                return await self.materialize(
                    trace_id,
                    worker_id=worker_id,
                    connection=conn,
                )

        conn = require_write_connection(connection)
        await conn.execute(
            "INSERT OR IGNORE INTO traces(trace_id, correlation_id, kind, entity_type, entity_id, "
            "payload_json, created_at_utc) "
            "SELECT trace_id, correlation_id, kind, entity_type, entity_id, payload_json, "
            "created_at_utc FROM trace_outbox "
            "WHERE trace_id = ? AND status = 'processing' AND lease_owner = ?",
            (str(trace_id), worker_id),
        )
        cursor = await conn.execute(
            "DELETE FROM trace_outbox WHERE trace_id = ? "
            "AND status = 'processing' AND lease_owner = ?",
            (str(trace_id), worker_id),
        )
        try:
            return cursor.rowcount == 1
        finally:
            await cursor.close()

    async def retry(
        self,
        trace_id: UUID,
        *,
        worker_id: str,
        now_utc: datetime,
        retry_delay: float,
        max_attempts: int,
        error_code: str,
        connection: aiosqlite.Connection | None = None,
    ) -> bool:
        """Release a failed claim, or retain it as a durable terminal failure."""

        if not worker_id:
            raise ValueError("worker_id must be non-empty")
        if retry_delay < 0:
            raise ValueError("retry_delay must not be negative")
        if max_attempts < 1:
            raise ValueError("max_attempts must be positive")
        if not error_code:
            raise ValueError("error_code must be non-empty")
        if connection is None:
            async with self.database.transaction(immediate=True) as conn:
                return await self.retry(
                    trace_id,
                    worker_id=worker_id,
                    now_utc=now_utc,
                    retry_delay=retry_delay,
                    max_attempts=max_attempts,
                    error_code=error_code,
                    connection=conn,
                )

        conn = require_write_connection(connection)
        now = _require_time(now_utc, "now_utc")
        cursor = await conn.execute(
            "SELECT attempt_count FROM trace_outbox WHERE trace_id = ? "
            "AND status = 'processing' AND lease_owner = ?",
            (str(trace_id), worker_id),
        )
        try:
            row = await cursor.fetchone()
        finally:
            await cursor.close()
        if row is None:
            return False

        terminal = int(row["attempt_count"]) >= max_attempts
        if terminal:
            status = "failed"
            available_at = now
        else:
            status = "pending"
            available_at = now + timedelta(seconds=retry_delay)
        cursor = await conn.execute(
            "UPDATE trace_outbox SET status = ?, available_at_utc = ?, "
            "lease_owner = NULL, lease_until_utc = NULL, last_error_code = ? "
            "WHERE trace_id = ? AND status = 'processing' AND lease_owner = ?",
            (status, utc_text(available_at), error_code, str(trace_id), worker_id),
        )
        await cursor.close()
        return terminal

    async def list_by_correlation(
        self,
        correlation_id: UUID,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[TraceRecord, ...]:
        conn = self.database.require_connection() if connection is None else connection
        cursor = await conn.execute(
            "SELECT * FROM traces WHERE correlation_id = ? ORDER BY created_at_utc, trace_id",
            (str(correlation_id),),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(_to_record(row) for row in rows)

    async def list_by_entity(
        self,
        entity_type: str,
        entity_id: str,
        *,
        connection: aiosqlite.Connection | None = None,
    ) -> tuple[TraceRecord, ...]:
        conn = self.database.require_connection() if connection is None else connection
        cursor = await conn.execute(
            "SELECT * FROM traces WHERE entity_type = ? AND entity_id = ? "
            "ORDER BY created_at_utc, trace_id",
            (entity_type, entity_id),
        )
        try:
            rows = await cursor.fetchall()
        finally:
            await cursor.close()
        return tuple(_to_record(row) for row in rows)


def _to_entry(row: aiosqlite.Row) -> TraceOutboxEntry:
    created_at = _require_time(parse_time(row["created_at_utc"]), "created_at_utc")
    available_at = _require_time(parse_time(row["available_at_utc"]), "available_at_utc")
    return TraceOutboxEntry(
        trace_id=UUID(row["trace_id"]),
        correlation_id=UUID(row["correlation_id"]),
        kind=row["kind"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        payload_json=row["payload_json"],
        created_at_utc=created_at,
        status=row["status"],
        attempt_count=int(row["attempt_count"]),
        available_at_utc=available_at,
        lease_owner=row["lease_owner"],
        lease_until_utc=parse_time(row["lease_until_utc"]),
        last_error_code=row["last_error_code"],
    )


def _to_record(row: aiosqlite.Row) -> TraceRecord:
    created_at = _require_time(parse_time(row["created_at_utc"]), "created_at_utc")
    payload = json.loads(row["payload_json"])
    if not isinstance(payload, dict):
        raise ValueError("trace payload must contain a JSON object")
    return TraceRecord(
        trace_id=UUID(row["trace_id"]),
        correlation_id=UUID(row["correlation_id"]),
        kind=row["kind"],
        entity_type=row["entity_type"],
        entity_id=row["entity_id"],
        payload=payload,
        created_at_utc=created_at,
    )


def _require_time(value: datetime | None, name: str) -> datetime:
    if value is None:
        raise ValueError(f"{name} must be a timestamp")
    return value


__all__ = ["TraceOutboxEntry", "TraceRecord", "TraceRepository"]
