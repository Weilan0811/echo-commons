from __future__ import annotations

import sqlite3
import time
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

from echo_commons.infrastructure.database.connection import Database


def initialize(database: Database, *, sql_directory: Path | None = None) -> int:
    root = sql_directory or files("echo_commons.infrastructure.database.sql")
    scripts = sorted(
        (item for item in root.iterdir() if item.name.endswith(".sql")), key=lambda item: item.name
    )
    connection = database.connect()
    try:
        deadline = time.monotonic() + 10
        while True:
            try:
                connection.execute("PRAGMA journal_mode = WAL")
                break
            except sqlite3.OperationalError as error:
                if (
                    error.sqlite_errorcode not in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
                    or time.monotonic() >= deadline
                ):
                    raise
                time.sleep(0.05)
        connection.execute(
            "CREATE TABLE IF NOT EXISTS schema_migrations ("
            "version INTEGER PRIMARY KEY CHECK(version > 0), applied_at_utc TEXT NOT NULL)"
        )
        applied = {row[0] for row in connection.execute("SELECT version FROM schema_migrations")}
        available = {int(script.name.split("_", 1)[0]) for script in scripts}
        if not applied <= available:
            raise ValueError("Database has migrations unavailable in this installation")
        for script in scripts:
            version = int(script.name.split("_", 1)[0])
            # 迁移在数据库写事务内重新检查，避免两个进程重复初始化。
            timestamp = datetime.now(UTC).isoformat(timespec="microseconds")
            connection.execute("BEGIN IMMEDIATE")
            exists = connection.execute(
                "SELECT 1 FROM schema_migrations WHERE version = ?", (version,)
            ).fetchone()
            if exists:
                connection.rollback()
                continue
            try:
                # 使用 SQLite 自带的语句识别，保持迁移及版本记录处于同一事务。
                statement = ""
                for line in script.read_text(encoding="utf-8").splitlines(keepends=True):
                    statement += line
                    if sqlite3.complete_statement(statement):
                        connection.execute(statement)
                        statement = ""
                if statement.strip():
                    raise ValueError(f"Incomplete SQL statement in {script.name}")
                connection.execute(
                    "INSERT INTO schema_migrations VALUES (?, ?)", (version, timestamp)
                )
                connection.commit()
            finally:
                if connection.in_transaction:
                    connection.rollback()
        return connection.execute(
            "SELECT COALESCE(MAX(version), 0) FROM schema_migrations"
        ).fetchone()[0]
    finally:
        connection.close()
