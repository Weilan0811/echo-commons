import argparse
import asyncio
import json
import sqlite3
import tempfile
import time
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.settings import load_settings
from echo_commons.execution.clock import utc_now
from echo_commons.modules.reflection.views import ViewScheduling
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import BusinessError


async def finish(app, community, character, graph_id):
    dispatcher = app.supervisor.workers["tasks-0"].dispatcher
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        with app.database.read() as connection:
            run = app.reflection.runs.get(connection, community, character, graph_id)
        if run.is_terminal:
            return run
        lease = await app.reflection_queue.claim(dispatcher.owner, utc_now())
        if lease:
            await dispatcher._execute(lease)
        else:
            await asyncio.sleep(0.1)
    raise TimeoutError("Relationship refresh did not finish")


def state(connection, community, character, target):
    row = connection.execute(
        "SELECT * FROM relationship_state WHERE community_id=? AND observer_character_id=? "
        "AND target_kind=? AND target_id=?",
        (community, character, target.kind.value, target.actor_id),
    ).fetchone()
    if row is None:
        raise ValueError("Requested relationship does not exist")
    return dict(row)


async def verify(database, relationships, output):
    output.mkdir(parents=True, exist_ok=True)
    with tempfile.TemporaryDirectory(prefix="echo-relationship-validation-") as directory:
        copy = Path(directory) / "relationships.sqlite3"
        with (
            closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(copy)) as destination,
        ):
            source.backup(destination)
        settings = load_settings().model_copy(
            update={
                "database_path": str(copy),
                "worker_enabled": False,
                "log_path": None,
                "asset_directory": str(Path(directory) / "assets"),
                "debug_capture_enabled": True,
                "debug_capture_path": str(output / "captures"),
            }
        )
        reports = []
        async with application_lifecycle(settings) as app:
            for community, character, kind, target_id in relationships:
                target = ActorRef(kind, target_id)
                with app.database.read() as connection:
                    before = state(connection, community, character, target)
                    old = connection.execute(
                        "SELECT r.* FROM reflection_graph_runs r JOIN memory_change_batches b "
                        "ON b.batch_id=r.source_id WHERE r.community_id=? AND r.character_id=? "
                        "AND r.graph_kind='view_refresh' AND r.status='partial' "
                        "AND EXISTS (SELECT 1 FROM json_each(b.materials_json) m "
                        "WHERE json_extract(m.value,'$.fact_kind')='relationship' "
                        "AND json_extract(m.value,'$.source_id')=?) "
                        "ORDER BY r.created_at_utc DESC LIMIT 1",
                        (community, character, f"{character}/{kind}/{target_id}"),
                    ).fetchone()
                    start_event = connection.execute(
                        "SELECT COALESCE(MAX(event_id),0) FROM task_execution_events"
                    ).fetchone()[0]
                recovery = None
                if old:
                    try:
                        recovered = app.reflection.restart(
                            community, character, old["graph_run_id"]
                        )
                    except BusinessError as error:
                        recovery = {"original_run": old["graph_run_id"], "error": error.code}
                    else:
                        completed = await finish(
                            app, community, character, str(recovered.graph_run_id)
                        )
                        recovery = {
                            "original_run": old["graph_run_id"],
                            "run": str(recovered.graph_run_id),
                            "status": completed.status,
                        }
                request = ViewScheduling(app.reflection).refresh_relationships(
                    community,
                    character,
                    str(uuid4()),
                    target,
                )[0]
                assert request["graph_run_id"], request
                run = await finish(app, community, character, request["graph_run_id"])
                assert run.status == "completed", run
                with app.database.read() as connection:
                    after = state(connection, community, character, target)
                    snapshot = app.reflection.runs.snapshot(
                        connection,
                        community,
                        character,
                        request["graph_run_id"],
                    )
                    events = connection.execute(
                        "SELECT payload_json FROM task_execution_events "
                        "WHERE event_id>? AND event_kind='run_finished'",
                        (start_event,),
                    ).fetchall()
                    usage = [json.loads(row[0])["observation"]["usage_summary"] for row in events]
                    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
                assert after["attitude_summary"].strip()
                assert (
                    len(after["attitude_summary"])
                    <= settings.reflection_relationship_attitude_max_chars
                )
                for field in (
                    "affection",
                    "trust",
                    "attachment",
                    "relationship_type",
                    "state_version",
                ):
                    assert before[field] == after[field], field
                reports.append(
                    {
                        "community": community,
                        "character": character,
                        "target": {"kind": kind, "actor_id": target_id},
                        "before": before,
                        "after": after,
                        "recovery": recovery,
                        "snapshot": snapshot.model_dump(mode="json"),
                        "model_requests": sum(item["model_request_count"] for item in usage),
                        "input_tokens": sum(item["input_tokens"] for item in usage),
                        "output_tokens": sum(item["output_tokens"] for item in usage),
                    }
                )
                print(
                    json.dumps(
                        {
                            "character": character,
                            "target": target_id,
                            "description": after["attitude_summary"],
                        },
                        ensure_ascii=False,
                    )
                )
        (output / "report.json").write_text(
            json.dumps(
                {"original_database_changed": False, "relationships": reports},
                ensure_ascii=False,
                indent=2,
            )
            + "\n",
            encoding="utf-8",
        )
        lines = ["# 关系描述实际修复结果", "", "在只读数据库的副本中验证，原数据库未修改。", ""]
        for item in reports:
            lines.extend(
                [
                    f"## {item['snapshot']['self']['name']} → "
                    f"{json.loads(item['snapshot']['materials'][0]['content'])['target_name']}",
                    "",
                    f"实际模型请求：{item['model_requests']} 次；输入 {item['input_tokens']}、"
                    f"输出 {item['output_tokens']} 词元。关系数值与状态版本保持相同。",
                    "",
                    item["after"]["attitude_summary"],
                    "",
                ]
            )
        (output / "report.md").write_text("\n".join(lines), encoding="utf-8")


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument(
        "--relationship",
        nargs=4,
        action="append",
        required=True,
        metavar=("COMMUNITY", "CHARACTER", "TARGET_KIND", "TARGET_ID"),
    )
    parser.add_argument("--output", type=Path, required=True)
    args = parser.parse_args()
    asyncio.run(verify(args.database.resolve(), args.relationship, args.output.resolve()))
