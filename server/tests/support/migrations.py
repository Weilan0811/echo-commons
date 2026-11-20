import json
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.migrations import initialize


def latest_version() -> int:
    return max(int(path.name[:4]) for path in files(
        "echo_commons.infrastructure.database.sql"
    ).iterdir() if path.name.endswith(".sql"))


def load_history(version: int, path: Path) -> Database:
    root = Path(__file__).resolve().parents[1] / "fixtures" / "migrations"
    fixture = json.loads((root / f"version-{version}.json").read_text(encoding="utf-8"))
    database = Database(path)
    with TemporaryDirectory() as directory:
        sql = Path(directory)
        for source in files("echo_commons.infrastructure.database.sql").iterdir():
            if source.name.endswith(".sql") and int(source.name[:4]) <= version:
                (sql / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        assert initialize(database, sql_directory=sql) == fixture["version"] == version
    connection = database.connect()
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("BEGIN IMMEDIATE")
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'memory_search_fts_%' AND name!='schema_migrations'"
            )
        ]
        for table in tables:
            connection.execute(f'DELETE FROM "{table}"')
        for table, rows in fixture["tables"].items():
            columns = tuple(rows[0])
            names = ",".join(f'"{name}"' for name in columns)
            connection.executemany(
                f'INSERT INTO "{table}" ({names}) VALUES ({",".join("?" for _ in columns)})',
                (tuple(row[column] for column in columns) for row in rows),
            )
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        connection.commit()
    finally:
        connection.close()
    return database
