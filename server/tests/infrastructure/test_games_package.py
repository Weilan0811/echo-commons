import asyncio
import shutil
import sqlite3
from importlib.resources import files

import pytest
from echo_games.public import GameService, GomokuCreateGameCommand, default_registry
from support.application import settings_for
from support.migrations import load_history

from echo_commons.app.composition import assemble
from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.infrastructure.realtime.stream import EventCursor
from echo_commons.shared.actors import ActorRef


def test_upgrade_from_version_20_preserves_real_community_and_game_transaction(tmp_path):
    scripts = tmp_path / "version20"
    scripts.mkdir()
    for item in files("echo_commons.infrastructure.database.sql").iterdir():
        if item.name.endswith(".sql") and int(item.name.split("_", 1)[0]) <= 20:
            shutil.copyfile(str(item), scripts / item.name)
    settings = settings_for(tmp_path, workers=False)
    database = load_history(19, settings.database_path)
    assert initialize(database, sql_directory=scripts) == 20
    with database.read() as connection:
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name != 'schema_migrations'"
            )
        ]
        tables = [
            table for table in tables if table not in {"social_candidates", "social_triggers"}
        ]
        columns = {
            table: ",".join(
                f'"{row[1]}"'
                for row in connection.execute(f'PRAGMA table_info("{table}")')
                if row[1] not in {"parent_turn_id", "depth", "root_turn_id"}
            )
            for table in tables
        }
        before = {
            table: [
                tuple(row) for row in connection.execute(f'SELECT {columns[table]} FROM "{table}"')
            ]
            for table in tables
        }
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_schema WHERE name LIKE 'game_%'"
            ).fetchone()[0]
            == 0
        )
    assert initialize(database) == initialize(database) == 29
    with database.read() as connection:
        assert {
            table: [
                tuple(row) for row in connection.execute(f'SELECT {columns[table]} FROM "{table}"')
            ]
            for table in tables
        } == before
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    service = GameService(default_registry())
    # 游戏与宿主的真实外键错误发生在同一事务，游戏创建也必须回滚。
    with pytest.raises(StorageError) as failure, database.transaction() as connection:
        receipt = service.create_game(
            connection, "alice", GomokuCreateGameCommand(request_id="create")
        )
        connection.execute(
            "INSERT INTO community_games VALUES (?,?,?)",
            (receipt.game_id, "community", "missing-conversation"),
        )
    assert isinstance(failure.value.__cause__, sqlite3.IntegrityError)
    with database.read() as connection:
        for table in (
            "game_games",
            "game_participations",
            "game_operation_receipts",
            "game_events",
        ):
            assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0
    with database.transaction() as connection:
        created = service.create_game(
            connection, "alice", GomokuCreateGameCommand(request_id="create")
        )
    with database.read() as connection:
        assert service.read_operation(connection, "alice", created.game_id, "create") == created


def test_notification_upgrade_preserves_cleaned_cursor_sequence_and_existing_rows(tmp_path):
    from datetime import UTC, datetime, timedelta

    from echo_commons.modules.communities.contracts import CreateGameSessionCommand

    scripts = tmp_path / "version22"
    scripts.mkdir()
    for item in files("echo_commons.infrastructure.database.sql").iterdir():
        if item.name.endswith(".sql") and int(item.name.split("_", 1)[0]) <= 22:
            shutil.copyfile(str(item), scripts / item.name)
    settings = settings_for(tmp_path, workers=False)
    database = load_history(19, settings.database_path)
    assert initialize(database, sql_directory=scripts) == 22
    with database.transaction() as connection:
        connection.execute(
            "UPDATE realtime_events SET created_at_utc=?",
            ((datetime.now(UTC) - timedelta(days=2)).isoformat(),),
        )
        assert database.events.clean(connection, datetime.now(UTC)) > 0
    with database.read() as connection:
        bounds = database.events.bounds(connection)
        position = EventCursor(player_id="alice", community_id="community", sequence=bounds[1])
        assert position.sequence > 0
        tables = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_schema WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name!='schema_migrations'"
            )
        ]
        before = {
            table: [tuple(row) for row in connection.execute(f'SELECT * FROM "{table}"')]
            for table in tables
        }
        columns = {
            table: ",".join(
                f'"{row[1]}"' for row in connection.execute(f'PRAGMA table_info("{table}")')
            )
            for table in tables
        }
        for removed in ("social_candidates", "social_triggers"):
            before.pop(removed)
        tables = tuple(before)
        bounds = database.events.bounds(connection)
    assert initialize(database) == initialize(database) == 29
    with database.read() as connection:
        assert {
            table: [
                tuple(row) for row in connection.execute(f'SELECT {columns[table]} FROM "{table}"')
            ]
            for table in tables
        } == before
        assert database.events.bounds(connection) == bounds
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    application = assemble(settings)
    created = application.game_participation.create_game(
        ActorRef("player", "alice"),
        CreateGameSessionCommand(
            community_id="community", game=GomokuCreateGameCommand(request_id="create")
        ),
    )
    outgoing, after, _, expired = application.realtime.scan(position)
    assert not expired and after.sequence > position.sequence
    assert any(
        item["event"] == "game.changed" and created.game_id in item["data"] for item in outgoing
    )


def test_failed_host_migration_rolls_back_game_schema_and_migration_record(tmp_path):
    scripts = tmp_path / "broken"
    scripts.mkdir()
    # 使用实际迁移编号，验证游戏包建表与宿主后续 SQL 共同回滚。
    (scripts / "0021_games.sql").write_text("CREATE TABLE invalid (id TEXT,);\n", encoding="utf-8")
    database = Database(tmp_path / "failed.sqlite3")
    with pytest.raises(sqlite3.OperationalError):
        initialize(database, sql_directory=scripts)
    with database.read() as connection:
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM sqlite_schema WHERE name LIKE 'game_%'"
            ).fetchone()[0]
            == 0
        )
        assert connection.execute("SELECT COUNT(*) FROM schema_migrations").fetchone()[0] == 0


def test_application_startup_loads_game_dependency_and_closes_normally(tmp_path):
    settings = settings_for(tmp_path, workers=False)

    async def run():
        async with application_lifecycle(settings) as application:
            assert application.started
            with application.database.read() as connection:
                assert (
                    connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                    == 29
                )
                assert connection.execute("SELECT COUNT(*) FROM game_games").fetchone()[0] == 0
        assert not application.started

    asyncio.run(run())
