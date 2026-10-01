"""Controlled aiosqlite connection and transaction helpers."""

from __future__ import annotations

import asyncio
from collections.abc import AsyncIterator
from contextlib import asynccontextmanager
from pathlib import Path
from uuid import uuid4

import aiosqlite


class Database:
    def __init__(self, path: str | Path) -> None:
        self.path = str(path)
        if self.path == ":memory:":
            # Independent connections are required for transaction isolation.  A
            # named shared-memory URI keeps that property available in tests too.
            self._target = f"file:echo-{uuid4()}?mode=memory&cache=shared"
            self._uri = True
        else:
            self._target = self.path
            self._uri = False
        self.connection: aiosqlite.Connection | None = None
        self._connect_lock = asyncio.Lock()
        self._write_lock = asyncio.Lock()

    @property
    def is_open(self) -> bool:
        return self.connection is not None

    async def connect(self) -> None:
        async with self._connect_lock:
            if self.connection is not None:
                return
            if self.path != ":memory:":
                Path(self.path).parent.mkdir(parents=True, exist_ok=True)
            connection = await self._open_connection()
            await connection.execute("PRAGMA journal_mode = WAL")
            await connection.commit()
            self.connection = connection

    async def _open_connection(self) -> aiosqlite.Connection:
        connection = await aiosqlite.connect(self._target, uri=self._uri)
        connection.row_factory = aiosqlite.Row
        await connection.execute("PRAGMA foreign_keys = ON")
        await connection.execute("PRAGMA busy_timeout = 5000")
        return connection

    async def close(self) -> None:
        async with self._connect_lock, self._write_lock:
            connection, self.connection = self.connection, None
            if connection is not None:
                await connection.close()

    def require_connection(self) -> aiosqlite.Connection:
        if self.connection is None:
            raise RuntimeError("database is not connected")
        return self.connection

    @asynccontextmanager
    async def transaction(self, *, immediate: bool = False) -> AsyncIterator[aiosqlite.Connection]:
        """Run one isolated transaction while serializing this process' writers.

        Reads use the long-lived connection.  Transactions use a separate
        connection so a concurrent reader can never observe or join an
        uncommitted T1/T2/T3 transaction on the same SQLite connection.
        """

        async with self._write_lock:
            self.require_connection()
            connection = await self._open_connection()
            try:
                await connection.execute("BEGIN IMMEDIATE" if immediate else "BEGIN")
                try:
                    yield connection
                except BaseException:
                    await connection.rollback()
                    raise
                else:
                    await connection.commit()
            finally:
                await connection.close()

    async def execute(self, sql: str, parameters: tuple[object, ...] = ()) -> aiosqlite.Cursor:
        connection = self.require_connection()
        return await connection.execute(sql, parameters)

    async def fetchone(self, sql: str, parameters: tuple[object, ...] = ()) -> aiosqlite.Row | None:
        cursor = await self.execute(sql, parameters)
        try:
            return await cursor.fetchone()
        finally:
            await cursor.close()

    async def fetchall(self, sql: str, parameters: tuple[object, ...] = ()) -> list[aiosqlite.Row]:
        cursor = await self.execute(sql, parameters)
        try:
            return await cursor.fetchall()
        finally:
            await cursor.close()
