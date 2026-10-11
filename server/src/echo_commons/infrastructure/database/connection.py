from __future__ import annotations

import logging
import sqlite3
from collections.abc import Callable, Iterator
from contextlib import contextmanager
from pathlib import Path

from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.infrastructure.realtime.repository import EventRepository
from echo_commons.shared.realtime import EventReference

logger = logging.getLogger(__name__)


class TransactionConnection(sqlite3.Connection):
    def __init__(self, *args, **kwargs):
        super().__init__(*args, **kwargs)
        self.events: dict[EventReference, None] = {}

    def record_event(self, event: EventReference) -> None:
        if not self.in_transaction:
            raise RuntimeError("Events require a business transaction")
        self.events[event] = None


class Database:
    def __init__(self, path: Path | str, *, read_only: bool = False) -> None:
        self.path = Path(path)
        self.read_only = read_only
        self.after_commit: Callable[[frozenset[str]], None] | None = None
        self.events = EventRepository()

    def connect(self) -> sqlite3.Connection:
        if not self.read_only:
            self.path.parent.mkdir(parents=True, exist_ok=True)
        try:
            target = self.path.resolve().as_uri() + "?mode=ro" if self.read_only else str(self.path)
            connection = sqlite3.connect(
                target,
                uri=self.read_only,
                timeout=10,
                isolation_level=None,
                factory=TransactionConnection,
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
            events = tuple(connection.events)
            if events:
                self.events.append(connection, events)
            connection.commit()
            if events and self.after_commit is not None:
                try:
                    self.after_commit(frozenset(event.community_id for event in events))
                except Exception:
                    logger.exception("Realtime notification failed after commit")
        except sqlite3.Error as error:
            raise StorageError(error) from error
        finally:
            if connection.in_transaction:
                connection.rollback()
            connection.close()
