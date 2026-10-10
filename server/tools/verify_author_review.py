import argparse
import asyncio
import json
import sqlite3
import tempfile
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.settings import load_settings


async def verify(database_path, community_id, character_id, player_id):
    with tempfile.TemporaryDirectory(prefix="echo-author-review-") as directory:
        target = Path(directory) / "review.sqlite3"
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
                "worker_enabled": False,
                "model_secrets_path": str(Path(directory) / "absent-secrets.toml"),
                "log_path": None,
                "asset_directory": str(Path(directory) / "assets"),
            }
        )
        async with application_lifecycle(settings) as application:
            application.characters.retry_memory(community_id, character_id, player_id=player_id)
            assert application.supervisor.workers["memory-initialization"].advance()
            with application.database.read() as connection:
                run_id = connection.execute(
                    "SELECT organization_run_id FROM memory_initializations WHERE character_id=?",
                    (character_id,),
                ).fetchone()[0]
                nodes = application.reflection.nodes.for_graph(connection, run_id)
                assert sum(node.status == "completed" for node in nodes) == 2
            lease = await application.reflection_queue.claim(
                "review-verification", datetime.now(UTC)
            )
            assert lease is not None
            with application.database.read() as connection:
                assert (
                    str(application.reflection.nodes.get(connection, lease.task_id).graph_run_id)
                    == run_id
                )
            result = application.reflection_graph_commit.commit(lease, datetime.now(UTC))
            assert result.decision_code == "approved", result
            with application.database.read() as connection:
                counts = {
                    table: connection.execute(
                        f"SELECT COUNT(*) FROM {table} WHERE character_id=?", (character_id,)
                    ).fetchone()[0]
                    for table in ("memory_entries", "memory_entities", "memory_edges")
                }
            print(
                json.dumps(
                    {
                        "decision": result.decision_code,
                        "counts": counts,
                        "model_calls": len(application.gateway._clients),
                    }
                )
            )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("community")
    parser.add_argument("character")
    parser.add_argument("player")
    arguments = parser.parse_args()
    asyncio.run(
        verify(
            arguments.database.resolve(), arguments.community, arguments.character, arguments.player
        )
    )
