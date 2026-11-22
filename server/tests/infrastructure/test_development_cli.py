import json
import os
import sqlite3
import subprocess
import sys
from pathlib import Path

import pytest

from echo_commons.app.settings import load_settings
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.errors import StorageError


def run_cli(*arguments, cwd):
    return subprocess.run(
        [sys.executable, "-m", "echo_commons.app.cli", *map(str, arguments)],
        cwd=cwd,
        env={**os.environ, "PYTHONUTF8": "1"},
        text=True,
        encoding="utf-8",
        capture_output=True,
        check=False,
    )


def test_cli_initializes_real_group_inspects_read_only_and_exports(tmp_path):
    configured = run_cli("configure", cwd=tmp_path)
    assert configured.returncode == 0, configured.stderr
    settings_path = Path(json.loads(configured.stdout)["settings_path"])
    secrets = settings_path.parent / "model-secrets.toml"
    assert secrets.is_file()
    original_secrets = secrets.read_bytes()
    original = load_settings()
    settings_path.write_text(
        settings_path.read_text(encoding="utf-8").replace(
            'secrets_path = "model-secrets.toml"',
            "secrets_path = " + json.dumps(original.model_secrets_path),
        ),
        encoding="utf-8",
    )
    arguments = ("--settings", settings_path)
    initialized = run_cli(*arguments, "init", "--example", cwd=tmp_path)
    assert initialized.returncode == 0, initialized.stderr
    facts = json.loads(initialized.stdout)
    assert facts["counts"] == {
        "communities": 1,
        "players": 2,
        "character_instances": 2,
        "conversations": 1,
        "messages": 0,
    }
    assert len(facts["actors"]) == 4
    repeated = run_cli(*arguments, "init", "--example", cwd=tmp_path)
    assert repeated.returncode == 0, repeated.stderr
    assert json.loads(repeated.stdout)["counts"] == facts["counts"]
    inspected = run_cli(*arguments, "inspect", cwd=tmp_path)
    assert inspected.returncode == 0, inspected.stderr
    assert json.loads(inspected.stdout)["counts"] == facts["counts"]
    destination = tmp_path / "exports" / "group.sqlite3"
    exported = run_cli(*arguments, "export", "--output", destination, cwd=tmp_path)
    assert exported.returncode == 0, exported.stderr
    database = Database(destination, read_only=True)
    with database.read() as connection:
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        assert connection.execute("SELECT COUNT(*) FROM character_instances").fetchone()[0] == 2
        assert (
            connection.execute("SELECT COUNT(*) FROM conversation_memberships").fetchone()[0] == 4
        )
        with pytest.raises(sqlite3.OperationalError, match="readonly"):
            connection.execute("DELETE FROM communities")
    refused = run_cli(*arguments, "export", "--output", destination, cwd=tmp_path)
    assert refused.returncode != 0
    assert "FileExistsError" in refused.stderr
    previous = settings_path.read_bytes()
    refused_config = run_cli("configure", cwd=tmp_path)
    assert refused_config.returncode != 0
    assert settings_path.read_bytes() == previous
    assert secrets.read_bytes() == original_secrets


def test_read_only_database_does_not_create_missing_database(tmp_path):
    path = tmp_path / "missing" / "database.sqlite3"
    with pytest.raises(StorageError), Database(path, read_only=True).read():
        pass
    assert not path.parent.exists()
