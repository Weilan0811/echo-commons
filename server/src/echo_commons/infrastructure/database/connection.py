from __future__ import annotations

import sqlite3
from collections.abc import Iterator
from contextlib import contextmanager
from pathlib import Path

from echo_commons.infrastructure.database.errors import StorageError


class Database:
    def __init__(self, path: Path | str, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only

    def connect(self) -> sqlite3.Connection:
        if not self.read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            target = self.path.resolve().as_uri() + "?mode=ro" if self.read_only else str(self.path)
            connection = sqlite3.connect(
                target, uri=self.read_only, timeout=10, isolation_level=None
            )
        except sqlite3.Error as error:
            raise StorageError(error) from error
        try:
            connection.row_factory = sqlite3.Row
            connection.execute("PRAGMA foreign_keys = ON")
            connection.execute("PRAGMA busy_timeout = 10000")
        except sqlite3.Error as error:
            connection.close()
            raise StorageError(error) from error
        return connection

    @contextmanager
    def read(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN")
            yield connection
        except sqlite3.Error as error:
            raise StorageError(error) from error
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()

    @contextmanager
    def transaction(self) -> Iterator[sqlite3.Connection]:
        connection = self.connect()
        try:
            connection.execute("BEGIN IMMEDIATE")
            yield connection
            connection.commit()
        except sqlite3.Error as error:
            raise StorageError(error) from error
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
