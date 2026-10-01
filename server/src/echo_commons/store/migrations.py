from __future__ import annotations

import sqlite3
from pathlib import Path

from echo_commons.store.database import Database

MIGRATIONS_DIR = Path(__file__).with_name("sql")


def _statements(script: str) -> tuple[str, ...]:
    """Split a SQLite script without sacrificing the surrounding transaction."""

    statements: list[str] = []
    buffer = ""
    for line in script.splitlines(keepends=True):
        buffer += line
        if sqlite3.complete_statement(buffer):
            statement = buffer.strip()
            if statement:
                statements.append(statement)
            buffer = ""
    if buffer.strip():
        raise ValueError("migration contains an incomplete SQL statement")
    return tuple(statements)


async def migrate(database: Database) -> None:
    await database.connect()
    async with database.transaction(immediate=True) as connection:
        await connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY, applied_at_utc TEXT NOT NULL)"
        )
        cursor = await connection.execute("SELECT COALESCE(MAX(version), 0) FROM schema_migrations")
        row = await cursor.fetchone()
        await cursor.close()
        current = int(row[0]) if row else 0
        migration_files = sorted(MIGRATIONS_DIR.glob("[0-9][0-9][0-9][0-9]_*.sql"))
        latest = max((int(path.name[:4]) for path in migration_files), default=0)
        if current > latest:
            raise RuntimeError(
                f"database schema version {current} is newer than supported version {latest}"
            )
        for migration_file in migration_files:
            version = int(migration_file.name[:4])
            if version <= current:
                continue
            for statement in _statements(migration_file.read_text(encoding="utf-8")):
                await connection.execute(statement)
            await connection.execute(
                "INSERT INTO schema_migrations(version, applied_at_utc) "
                "VALUES (?, strftime('%Y-%m-%dT%H:%M:%fZ','now'))",
                (version,),
            )
        await connection.execute(
            "INSERT INTO meta(key, value) VALUES('schema_version', ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (str(latest),),
        )
