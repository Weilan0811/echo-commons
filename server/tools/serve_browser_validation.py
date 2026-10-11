import argparse
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

import uvicorn

from echo_commons.app.main import create_app
from echo_commons.app.settings import load_settings


def serve(database_path, port, origin):
    with tempfile.TemporaryDirectory(prefix="echo-browser-validation-") as directory:
        print(f"Validation directory: {directory}", flush=True)
        target = Path(directory) / "validation.sqlite3"
        if database_path:
            with (
                closing(
                    sqlite3.connect(f"file:{database_path.as_posix()}?mode=ro", uri=True)
                ) as source,
                closing(sqlite3.connect(target)) as destination,
            ):
                source.backup(destination)
        settings = load_settings().model_copy(
            update={
                "database_path": str(target),
                "asset_directory": str(Path(directory) / "assets"),
                "worker_enabled": False,
                "model_secrets_path": str(Path(directory) / "absent-secrets.toml"),
                "log_path": None,
                "debug_capture_enabled": False,
                "cors_origins": [origin],
            }
        )
        uvicorn.run(create_app(settings), host="127.0.0.1", port=port, access_log=False)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--database", type=Path)
    parser.add_argument("--port", type=int, default=8877)
    parser.add_argument("--origin", default="http://127.0.0.1:5175")
    arguments = parser.parse_args()
    serve(
        arguments.database.resolve() if arguments.database else None,
        arguments.port,
        arguments.origin,
    )
