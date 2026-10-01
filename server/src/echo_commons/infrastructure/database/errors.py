import sqlite3


class StorageError(RuntimeError):
    def __init__(self, error: sqlite3.Error) -> None:
        self.sqlite_code = error.sqlite_errorcode
        self.code = error.sqlite_errorname.lower()
        self.retryable = (self.sqlite_code & 255) in (sqlite3.SQLITE_BUSY, sqlite3.SQLITE_LOCKED)
        super().__init__(self.code)
