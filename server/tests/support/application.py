import os

from echo_commons.app.settings import load_settings


def settings_for(tmp_path, *, workers):
    return load_settings(
        os.environ.get("ECHO_COMMONS_TEST_SETTINGS", "config/settings.toml")
    ).model_copy(
        update={
            "database_path": str(tmp_path / "application.sqlite3"),
            "asset_directory": str(tmp_path / "assets/images"),
            "worker_enabled": workers,
            "quiet_window_seconds": 0,
            "worker_poll_interval_seconds": 0.03,
            "shutdown_timeout_seconds": 5,
            "log_path": str(tmp_path / "logs/echo.log"),
        }
    )
