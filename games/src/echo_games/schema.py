import sqlite3
from importlib.resources import files


def create_schema(connection: sqlite3.Connection) -> None:
    if not connection.in_transaction:
        raise RuntimeError("Game schema requires a caller-owned transaction")
    script = files("echo_games.sql").joinpath("0001_games.sql").read_text(encoding="utf-8")
    # executescript 会提交当前事务，逐条执行以保留宿主迁移的共同事务。
    statement = ""
    for line in script.splitlines(keepends=True):
        statement += line
        if sqlite3.complete_statement(statement):
            connection.execute(statement)
            statement = ""
    if statement.strip():
        raise ValueError("Incomplete game schema SQL")
