from __future__ import annotations

import json
import subprocess
import sys
from pathlib import Path

import pytest

from echo_commons.config import DEFAULT_DATABASE_PATH
from echo_commons.store.database import Database
from echo_commons.store.migrations import migrate

TOOL_PATH = Path(__file__).resolve().parents[2] / "tools" / "dev" / "echo_runtime_data.py"


def _run_tool(*arguments: str) -> dict[str, object]:
    result = subprocess.run(
        [sys.executable, str(TOOL_PATH), *arguments],
        check=True,
        capture_output=True,
        encoding="utf-8",
        text=True,
    )
    return json.loads(result.stdout)


def _run_tool_failure(*arguments: str) -> subprocess.CompletedProcess[str]:
    return subprocess.run(
        [sys.executable, str(TOOL_PATH), *arguments],
        capture_output=True,
        encoding="utf-8",
        text=True,
    )


def test_scenario_list_exposes_versioned_named_cases() -> None:
    payload = _run_tool("scenario", "list")

    assert payload["format_version"] == 1
    scenarios = {item["id"]: item for item in payload["scenarios"]}
    assert set(scenarios) == {
        "relationship-lifecycle",
        "relationship-type-matrix",
        "soft-state",
        "activity-expiry",
        "replay-and-version-conflict",
        "absence-multi-day",
    }
    assert scenarios["relationship-lifecycle"]["rounds"][-1] == "qualifying-support-2"


def test_lifecycle_round_can_be_rebuilt_and_inspected(tmp_path: Path) -> None:
    database_path = tmp_path / "lifecycle.sqlite3"

    first = _run_tool(
        "scenario",
        "apply",
        "--name",
        "relationship-lifecycle",
        "--round",
        "2",
        "--database",
        str(database_path),
    )
    assert first["round_id"] == "first-interaction"
    first_inspection = _run_tool("scenario", "inspect", "--database", str(database_path))
    first_relationship = first_inspection["relationship_state"]
    assert first_relationship["relationship_type"] == "acquaintance"
    assert first_relationship["affection"] == 60.0
    assert first_relationship["trust"] == 60.0

    final = _run_tool(
        "scenario",
        "apply",
        "--name",
        "relationship-lifecycle",
        "--round",
        "4",
        "--database",
        str(database_path),
    )
    assert final["round_id"] == "qualifying-support-2"
    inspection = _run_tool("scenario", "inspect", "--database", str(database_path))
    relationship = inspection["relationship_state"]
    assert relationship["relationship_type"] == "friend"
    assert relationship["affection"] == pytest.approx(74.4)
    assert relationship["trust"] == pytest.approx(74.4)
    assert relationship["attachment"] == pytest.approx(14.2625)
    assert inspection["world"]["phase"] == "afternoon"
    assert "74.4" not in inspection["prompt_projection"]["relationship"]
    assert "local-player" not in inspection["prompt_projection"]["relationship"]


def test_type_matrix_keeps_scores_but_changes_projection(tmp_path: Path) -> None:
    database_path = tmp_path / "matrix.sqlite3"

    _run_tool(
        "scenario",
        "apply",
        "--name",
        "relationship-type-matrix",
        "--round",
        "2",
        "--database",
        str(database_path),
    )
    acquaintance = _run_tool("scenario", "inspect", "--database", str(database_path))
    _run_tool(
        "scenario",
        "apply",
        "--name",
        "relationship-type-matrix",
        "--round",
        "3",
        "--database",
        str(database_path),
    )
    friend = _run_tool("scenario", "inspect", "--database", str(database_path))

    assert acquaintance["relationship_state"]["relationship_type"] == "acquaintance"
    assert friend["relationship_state"]["relationship_type"] == "friend"
    assert (
        acquaintance["relationship_state"]["affection"]
        == friend["relationship_state"]["affection"]
        == 70.0
    )
    assert (
        acquaintance["relationship_state"]["trust"] == friend["relationship_state"]["trust"] == 70.0
    )
    assert "朋友" not in acquaintance["prompt_projection"]["relationship"]
    assert "朋友" in friend["prompt_projection"]["relationship"]


def test_activity_expiry_and_replacement_are_time_deterministic(tmp_path: Path) -> None:
    database_path = tmp_path / "activity.sqlite3"

    _run_tool(
        "scenario",
        "apply",
        "--name",
        "activity-expiry",
        "--round",
        "1",
        "--database",
        str(database_path),
    )
    active = _run_tool("scenario", "inspect", "--database", str(database_path))
    assert active["character_state"]["current_activity"] == "修改一幅画"
    expired_at_future_time = _run_tool(
        "scenario",
        "inspect",
        "--database",
        str(database_path),
        "--at",
        "2026-09-16T03:00:00Z",
    )
    assert expired_at_future_time["character_state"]["current_activity"] == ""

    _run_tool(
        "scenario",
        "apply",
        "--name",
        "activity-expiry",
        "--round",
        "2",
        "--database",
        str(database_path),
    )
    expired = _run_tool("scenario", "inspect", "--database", str(database_path))
    assert expired["character_state"]["current_activity"] == ""

    _run_tool(
        "scenario",
        "apply",
        "--name",
        "activity-expiry",
        "--round",
        "3",
        "--database",
        str(database_path),
    )
    replaced = _run_tool("scenario", "inspect", "--database", str(database_path))
    assert replaced["character_state"]["current_activity"] == "出门散步"


def test_snapshot_restore_rebuilds_the_same_state_slice(tmp_path: Path) -> None:
    database_path = tmp_path / "source.sqlite3"
    restored_path = tmp_path / "restored.sqlite3"
    snapshot_path = tmp_path / "state.snapshot.json"
    restored_snapshot_path = tmp_path / "restored.snapshot.json"

    _run_tool(
        "scenario",
        "apply",
        "--name",
        "relationship-lifecycle",
        "--round",
        "4",
        "--database",
        str(database_path),
    )
    _run_tool(
        "scenario",
        "snapshot",
        "--database",
        str(database_path),
        "--output",
        str(snapshot_path),
    )
    _run_tool(
        "scenario",
        "restore",
        "--database",
        str(restored_path),
        "--input",
        str(snapshot_path),
    )
    _run_tool(
        "scenario",
        "snapshot",
        "--database",
        str(restored_path),
        "--output",
        str(restored_snapshot_path),
    )

    source = json.loads(snapshot_path.read_text(encoding="utf-8"))
    restored = json.loads(restored_snapshot_path.read_text(encoding="utf-8"))
    assert source == restored


def test_snapshot_restore_rejects_data_outside_the_fixture(tmp_path: Path) -> None:
    database_path = tmp_path / "source.sqlite3"
    snapshot_path = tmp_path / "state.snapshot.json"
    edited_snapshot_path = tmp_path / "edited.snapshot.json"
    restored_path = tmp_path / "restored.sqlite3"

    _run_tool(
        "scenario",
        "apply",
        "--name",
        "relationship-lifecycle",
        "--round",
        "4",
        "--database",
        str(database_path),
    )
    _run_tool(
        "scenario",
        "snapshot",
        "--database",
        str(database_path),
        "--output",
        str(snapshot_path),
    )
    edited = json.loads(snapshot_path.read_text(encoding="utf-8"))
    edited["tables"]["world_state"][0]["phase"] = "tampered"
    edited_snapshot_path.write_text(json.dumps(edited, ensure_ascii=False), encoding="utf-8")

    result = _run_tool_failure(
        "scenario",
        "restore",
        "--database",
        str(restored_path),
        "--input",
        str(edited_snapshot_path),
    )

    assert result.returncode != 0
    assert "does not match" in result.stderr
    assert not restored_path.exists()


@pytest.mark.asyncio
async def test_scenario_apply_refuses_unmarked_database(tmp_path: Path) -> None:
    database_path = tmp_path / "unmarked.sqlite3"
    database = Database(database_path)
    await migrate(database)
    await database.close()

    result = _run_tool_failure(
        "scenario",
        "apply",
        "--name",
        "soft-state",
        "--database",
        str(database_path),
    )

    assert result.returncode != 0
    assert "unmarked database" in result.stderr


def test_scenario_apply_refuses_the_user_runtime_database() -> None:
    result = _run_tool_failure(
        "scenario",
        "apply",
        "--name",
        "soft-state",
        "--database",
        DEFAULT_DATABASE_PATH,
    )

    assert result.returncode != 0
    assert "user runtime database" in result.stderr
