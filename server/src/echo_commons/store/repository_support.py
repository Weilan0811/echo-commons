"""Shared SQLite repository serialization and connection helpers."""

from __future__ import annotations

import json
from datetime import UTC, datetime

import aiosqlite

from echo_server.store.database import Database


def utc_text(value: datetime) -> str:
    if value.tzinfo is None:
        value = value.replace(tzinfo=UTC)
    return value.astimezone(UTC).isoformat(timespec="milliseconds").replace("+00:00", "Z")


def parse_time(value: str | None) -> datetime | None:
    if value is None:
        return None
    return datetime.fromisoformat(value.replace("Z", "+00:00")).astimezone(UTC)


def as_json(value: object) -> str:
    return json.dumps(value, ensure_ascii=False, separators=(",", ":"), sort_keys=True)


def get_connection(
    database: Database, connection: aiosqlite.Connection | None
) -> aiosqlite.Connection:
    return connection or database.require_connection()


def require_write_connection(connection: aiosqlite.Connection | None) -> aiosqlite.Connection:
    if connection is None:
        raise RuntimeError("repository writes require an explicit transaction connection")
    return connection
