from pathlib import Path

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.migrations import initialize


def copy_to_historical_schema(source: Database, sql_directory: Path, path: Path) -> Database:
    # 将真实业务记录按历史列复制到真实旧库，避免当前业务入口依赖旧库不存在的字段。
    target = Database(path)
    initialize(target, sql_directory=sql_directory)
    connection = target.connect()
    try:
        connection.execute("PRAGMA foreign_keys=OFF")
        connection.execute("ATTACH DATABASE ? AS current_data", (str(source.path),))
        connection.execute("BEGIN IMMEDIATE")
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'memory_search_fts_%' AND name!='schema_migrations'"
            )
        ]
        for table in tables:
            columns = [row[1] for row in connection.execute(f'PRAGMA table_info("{table}")')]
            names = ",".join(f'"{name}"' for name in columns)
            connection.execute(
                f'INSERT INTO "{table}" ({names}) SELECT {names} FROM current_data."{table}"'
            )
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        connection.commit()
    finally:
        connection.close()
    return target
