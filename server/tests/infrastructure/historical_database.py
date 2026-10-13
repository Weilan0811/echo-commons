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
            connection.execute(f'DELETE FROM "{table}"')
            source_table = (
                "conversation_operations"
                if table == "conversation_membership_operations"
                else table
            )
            source_columns = {
                row[1]
                for row in connection.execute(f'PRAGMA current_data.table_info("{source_table}")')
            }
            if not source_columns:
                # 当前记录没有已删除的表，历史表保持空白。
                continue
            selections = []
            for column in columns:
                if table == "memory_entries" and column in {"subject_kind", "subject_id"}:
                    assert (
                        connection.execute(
                            "SELECT 1 FROM current_data.memory_entries "
                            "WHERE source_kind!='blueprint_preload' LIMIT 1"
                        ).fetchone()
                        is None
                    )
                    # 模板预置页的历史主体就是创建时的角色身份。
                    selections.append("'character'" if column == "subject_kind" else "character_id")
                else:
                    assert column in source_columns
                    selections.append(f'"{column}"')
            projection = ",".join(selections)
            connection.execute(
                f'INSERT INTO "{table}" ({names}) SELECT {projection} '
                f'FROM current_data."{source_table}"'
            )
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        connection.commit()
    finally:
        connection.close()
    return target
