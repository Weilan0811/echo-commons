from __future__ import annotations

import aiosqlite

from echo_commons.store.database import Database


class MetaRepository:
    def __init__(self, database: Database) -> None:
        self.database = database

    async def get(self, key: str) -> str | None:
        row = await self.database.fetchone("SELECT value FROM meta WHERE key = ?", (key,))
        return row["value"] if row else None

    async def set(
        self, key: str, value: str, connection: aiosqlite.Connection | None = None
    ) -> None:
        if connection is None:
            raise RuntimeError("repository writes require an explicit transaction connection")
        conn = connection
        await conn.execute(
            "INSERT INTO meta(key, value) VALUES (?, ?) "
            "ON CONFLICT(key) DO UPDATE SET value = excluded.value",
            (key, value),
        )
