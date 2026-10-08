import asyncio
import os
import subprocess
import sys
from pathlib import Path

import pytest
from test_application_lifecycle import settings_for

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.shared.actors import ActorRef


@pytest.mark.model
def test_killed_real_model_process_recovers_original_tasks(tmp_path):
    settings = settings_for(tmp_path, workers=False)

    async def seed():
        async with application_lifecycle(settings) as application:
            application.communities.create("社群", "Asia/Shanghai", community_id="community")
            application.communities.update("community", expected_version=0, status="active")
            application.communities.register_player("玩家", player_id="player")
            application.communities.join("community", ActorRef("player", "player"))
            for character in ("one", "two"):
                application.characters.create("community", "xiaojin", character_id=character)
            application.conversations.create(
                "community",
                "group",
                (
                    ActorRef("player", "player"),
                    ActorRef("character", "one"),
                    ActorRef("character", "two"),
                ),
                conversation_id="conversation",
            )
            application.intake.send(
                "community",
                "conversation",
                PlayerMessage("player", "hello", "大家好，请各位聊聊今天想一起做的事情。"),
            )
            application.planner.plan()
            with application.database.read() as connection:
                snapshots = {
                    row["task_id"]: row["snapshot_json"]
                    for row in connection.execute("SELECT * FROM conversation_tasks")
                }
            return application.database, snapshots

    database, snapshots = asyncio.run(seed())
    log_path = tmp_path / "worker.jsonl"
    output_path = tmp_path / "process-output.txt"
    command = [
        sys.executable,
        str(Path(__file__).with_name("run_worker_process.py")),
        "--database",
        settings.database_path,
        "--log",
        str(log_path),
        "--registry",
        settings.model_registry_path,
        "--secrets",
        settings.model_secrets_path,
    ]
    with output_path.open("w", encoding="utf-8") as output:
        process = subprocess.Popen(
            command,
            stdout=output,
            stderr=output,
            creationflags=subprocess.CREATE_NO_WINDOW if os.name == "nt" else 0,
        )
        try:

            async def wait_for_request():
                async with asyncio.timeout(30):
                    while not (
                        log_path.exists()
                        and "model.call.started" in log_path.read_text(encoding="utf-8")
                    ):
                        assert process.poll() is None, output_path.read_text(encoding="utf-8")
                        await asyncio.sleep(0.02)

            asyncio.run(wait_for_request())
            with database.read() as connection:
                row = connection.execute(
                    "SELECT * FROM conversation_tasks WHERE status = 'processing'"
                ).fetchone()
                assert row is not None
                interrupted_task = row["task_id"]
                assert row["attempt_count"] == 1
            process.terminate()
            process.wait(timeout=10)
        finally:
            if process.poll() is None:
                process.kill()
                process.wait(timeout=10)

    restarted_settings = settings.model_copy(update={"worker_enabled": True})

    async def restart():
        async with application_lifecycle(restarted_settings) as application:
            async with asyncio.timeout(90):
                while True:
                    with database.read() as connection:
                        rows = connection.execute("SELECT * FROM conversation_tasks").fetchall()
                        if all(row["status"] == "completed" for row in rows):
                            assert {
                                row["task_id"]: row["snapshot_json"] for row in rows
                            } == snapshots
                            recovered = next(
                                row for row in rows if row["task_id"] == interrupted_task
                            )
                            assert (
                                recovered["attempt_count"] == 2
                                and recovered["lease_generation"] == 2
                            )
                            assert (
                                connection.execute(
                                    "SELECT COUNT(*) FROM messages WHERE sender_kind = 'character'"
                                ).fetchone()[0]
                                == 2
                            )
                            break
                    await asyncio.sleep(0.1)
            clients = tuple(application.gateway._clients.values())
        assert all(client.is_closed() for client in clients)

    asyncio.run(restart())
