import json
from importlib.resources import files
from pathlib import Path
from tempfile import TemporaryDirectory

import echo_games
from fastapi.testclient import TestClient

import echo_commons
from echo_commons.app.main import create_app
from echo_commons.app.settings import load_settings


def main() -> None:
    for module in (echo_games, echo_commons):
        assert "site-packages" in Path(module.__file__).resolve().parts
    with TemporaryDirectory(prefix="echo-games-host-installed-") as temporary:
        directory = Path(temporary)
        config = files("echo_commons").joinpath("resources/config/settings.toml")
        settings = load_settings(str(config)).model_copy(
            update={
                "database_path": str(directory / "application.sqlite3"),
                "asset_directory": str(directory / "assets"),
                "log_path": str(directory / "application.log"),
                "model_secrets_path": str(directory / "missing-secrets.toml"),
                "debug_capture_enabled": False,
                "worker_enabled": False,
            }
        )
        with TestClient(create_app(settings)) as client:
            assert client.get("/health/ready").status_code == 200
            database = client.app.state.application.database
            with database.read() as connection:
                assert (
                    connection.execute("SELECT MAX(version) FROM schema_migrations").fetchone()[0]
                    == 21
                )
                assert connection.execute("SELECT COUNT(*) FROM game_games").fetchone()[0] == 0
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        print(
            json.dumps(
                {
                    "host_startup": "passed",
                    "migration": 21,
                    "game_sql_resources": "passed",
                    "model_calls": 0,
                }
            )
        )


if __name__ == "__main__":
    main()
