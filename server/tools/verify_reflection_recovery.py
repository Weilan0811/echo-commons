import argparse
import asyncio
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.settings import load_settings
from echo_commons.execution.clock import utc_now


async def verify(database_path: Path, graph_id: str):
    with tempfile.TemporaryDirectory(prefix="echo-reflection-recovery-") as directory:
        target = Path(directory) / "recovery.sqlite3"
        with (
            closing(sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(target)) as destination,
        ):
            source.backup(destination)
        settings = load_settings().model_copy(
            update={
                "database_path": str(target),
                "worker_enabled": False,
                "log_path": str(Path(directory) / "recovery.log"),
                "asset_directory": str(Path(directory) / "assets"),
            }
        )
        async with application_lifecycle(settings) as app:
            with app.database.read() as connection:
                scope = app.reflection.runs.scope(connection, graph_id)
                previous = app.reflection.nodes.for_graph(connection, graph_id)
                original_artifacts = {
                    node.node_key: str(node.artifact_id)
                    for node in previous
                    if node.status == "completed" and node.node_key != "view_aggregate"
                }
                before = connection.execute(
                    "SELECT COALESCE(MAX(event_id),0) FROM task_execution_events"
                ).fetchone()[0]
            resumed = app.reflection.restart(scope.community_id, scope.character_id, graph_id)
            dispatcher = app.supervisor.workers["reflection-0"].dispatcher
            for _ in range(32):
                with app.database.read() as connection:
                    current = app.reflection.runs.get(
                        connection, scope.community_id, scope.character_id,
                        str(resumed.graph_run_id)
                    )
                if current.is_terminal:
                    break
                lease = await app.reflection_queue.claim(dispatcher.owner, utc_now())
                if lease is None:
                    await asyncio.sleep(1)
                    continue
                await dispatcher._execute(lease)
            assert current.status == "completed", current
            with app.database.read() as connection:
                nodes = app.reflection.nodes.for_graph(connection, str(resumed.graph_run_id))
                assert all(node.is_terminal for node in nodes)
                for key, artifact_id in original_artifacts.items():
                    old = app.reflection_commit.artifacts.get(connection, graph_id, artifact_id)
                    node = next(node for node in nodes if node.node_key == key)
                    restored = app.reflection_commit.artifacts.get(
                        connection, str(resumed.graph_run_id), str(node.artifact_id)
                    )
                    assert restored.payload == old.payload
                review = app.reflection_graph_commit.results.for_graph(
                    connection, str(resumed.graph_run_id)
                )
                events = connection.execute(
                    "SELECT payload_json FROM task_execution_events "
                    "WHERE event_id>? AND event_kind='run_finished'", (before,)
                ).fetchall()
                usage = [json.loads(row[0])["observation"]["usage_summary"] for row in events]
            assert app.reflection_graph_commit.commit(
                lease, utc_now()
            ).result_id == review.result_id
            print(json.dumps({
                "original_run": graph_id,
                "recovered_run": str(resumed.graph_run_id),
                "status": current.status,
                "reused_nodes": sorted(original_artifacts),
                "model_requests": sum(item["model_request_count"] for item in usage),
                "input_tokens": sum(item["input_tokens"] for item in usage),
                "output_tokens": sum(item["output_tokens"] for item in usage),
                "original_database_changed": False,
            }))


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("graph_run_id")
    arguments = parser.parse_args()
    asyncio.run(verify(arguments.database.resolve(), arguments.graph_run_id))
