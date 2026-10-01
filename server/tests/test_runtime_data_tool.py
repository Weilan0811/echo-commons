from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from echo_commons.store.database import Database
from echo_commons.store.migrations import migrate

TOOL_PATH = Path(__file__).resolve().parents[2] / "tools" / "dev" / "echo_runtime_data.py"


def test_runtime_data_tool_seeds_and_exports_a_complete_scenario(tmp_path):
    database_path = tmp_path / "runtime.sqlite3"
    export_path = tmp_path / "runtime.json"

    seed = subprocess.run(
        [sys.executable, str(TOOL_PATH), "init", "--database", str(database_path)],
        check=True,
        capture_output=True,
        text=True,
    )
    assert '"conversation_id": "s2-5-demo"' in seed.stdout

    subprocess.run(
        [
            sys.executable,
            str(TOOL_PATH),
            "export",
            "--database",
            str(database_path),
            "--output",
            str(export_path),
        ],
        check=True,
        capture_output=True,
        text=True,
    )

    exported = json.loads(export_path.read_text(encoding="utf-8"))
    assert exported["format_version"] == 1
    assert exported["tables"]["world_state"][0]["status"] == "active"
    assert exported["tables"]["character_states"][0]["character_id"] == "xiaojin"
    assert exported["tables"]["input_batches"][0]["status"] == "covered"
    assert exported["tables"]["conversation_tasks"][0]["status"] == "completed"
    assert exported["tables"]["agent_results"][0]["status"] == "approved"
    assert exported["tables"]["trace_outbox"] == []
    assert exported["tables"]["character_state_entries"] == []
    assert exported["tables"]["relationship_state"] == []
    assert exported["tables"]["relation_evidence"] == []
    assert [message["text"] for message in exported["tables"]["messages"]] == [
        "今天过得怎么样？",
        "还不错。",
        "你呢？",
    ]


@pytest.mark.asyncio
async def test_runtime_data_tool_refuses_to_seed_database_with_s5_state(tmp_path):
    database_path = tmp_path / "runtime.sqlite3"
    database = Database(str(database_path))
    await migrate(database)
    async with database.transaction(immediate=True) as connection:
        await connection.execute(
            "INSERT INTO relationship_state(account_id, observer_character_id, target_kind, "
            "target_id, relationship_type, state_version, updated_at_utc) "
            "VALUES ('local-player', 'xiaojin', 'account', 'local-player', 'stranger', 0, "
            "'2026-09-05T12:00:00Z')"
        )
    await database.close()

    result = subprocess.run(
        [sys.executable, str(TOOL_PATH), "init", "--database", str(database_path)],
        capture_output=True,
        text=True,
    )

    assert result.returncode != 0
    assert "refusing to seed non-empty table 'relationship_state'" in result.stderr
