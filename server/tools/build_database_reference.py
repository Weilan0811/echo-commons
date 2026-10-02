import argparse
from pathlib import Path
from tempfile import TemporaryDirectory

from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.migrations import initialize

INTRODUCTION = (
    Path(__file__).with_name("database-reference-introduction.md").read_text(encoding="utf-8")
)


def quote_name(name: str) -> str:
    return '"' + name.replace('"', '""') + '"'


def cell(value) -> str:
    return "—" if value is None else str(value).replace("|", "\\|").replace("\n", " ")


def reference() -> str:
    with TemporaryDirectory(prefix="echo-commons-schema-") as temporary:
        database = Database(Path(temporary) / "schema.sqlite3")
        initialize(database)
        with database.read() as connection:
            shadow = {
                row["name"]
                for row in connection.execute("PRAGMA table_list")
                if row["type"] == "shadow"
            }
            tables = [
                row
                for row in connection.execute(
                    "SELECT name,sql FROM sqlite_schema WHERE type='table' "
                    "AND name NOT LIKE 'sqlite_%' ORDER BY rowid"
                )
                if row["name"] not in shadow
            ]
            lines = [INTRODUCTION, f"实际登记 {len(tables)} 张表，包含迁移登记及 FTS5 虚拟表。\n"]
            for table in tables:
                name = table["name"]
                lines.extend(
                    [
                        f"\n## `{name}`\n",
                        "| 字段 | SQLite 类型 | 允许空值 | 默认值 | 主键顺序 |",
                        "|---|---|---|---|---|",
                    ]
                )
                for column in connection.execute(f"PRAGMA table_info({quote_name(name)})"):
                    lines.append(
                        f"| `{column['name']}` | {cell(column['type'])} | "
                        f"{'否' if column['notnull'] else '是'} | "
                        f"{cell(column['dflt_value'])} | {column['pk'] or '—'} |"
                    )
                foreign_keys = connection.execute(
                    f"PRAGMA foreign_key_list({quote_name(name)})"
                ).fetchall()
                if foreign_keys:
                    lines.extend(
                        [
                            "\n### 外键\n",
                            "| 组合编号 | 本表字段 | 目标表 | 目标字段 | 更新规则 | 删除规则 |",
                            "|---|---|---|---|---|---|",
                        ]
                    )
                    for key in foreign_keys:
                        lines.append(
                            f"| {key['id']} | `{key['from']}` | `{key['table']}` | "
                            f"`{key['to']}` | {key['on_update']} | {key['on_delete']} |"
                        )
                indexes = connection.execute(f"PRAGMA index_list({quote_name(name)})").fetchall()
                if indexes:
                    lines.extend(
                        [
                            "\n### 索引与唯一键\n",
                            "| 名称 | 唯一 | 字段顺序 | 部分索引 |",
                            "|---|---|---|---|",
                        ]
                    )
                    for index in indexes:
                        columns = connection.execute(
                            f"PRAGMA index_info({quote_name(index['name'])})"
                        ).fetchall()
                        lines.append(
                            f"| `{index['name']}` | {'是' if index['unique'] else '否'} | "
                            f"{', '.join(cell(column['name']) for column in columns)} | "
                            f"{'是' if index['partial'] else '否'} |"
                        )
                        sql = connection.execute(
                            "SELECT sql FROM sqlite_schema WHERE type='index' AND name=?",
                            (index["name"],),
                        ).fetchone()[0]
                        if sql:
                            lines.append(f"\n```sql\n{sql};\n```\n")
                lines.append(f"\n### 完整建表约束\n\n```sql\n{table['sql']};\n```\n")
    return "\n".join(lines).rstrip() + "\n"


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--check", action="store_true")
    arguments = parser.parse_args()
    target = Path(__file__).resolve().parents[1] / "docs/database-design.md"
    content = reference()
    if arguments.check:
        if target.read_text(encoding="utf-8") != content:
            raise ValueError("Database reference differs from the current schema")
    else:
        target.write_text(content, encoding="utf-8")
    print("Database reference verified" if arguments.check else "Database reference generated")


if __name__ == "__main__":
    main()
