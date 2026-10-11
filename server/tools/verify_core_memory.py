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
from echo_commons.modules.communities.domain import CommunityStatus
from echo_commons.modules.conversations.domain.conversation import ConversationKind
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.reflection.views import ViewScheduling
from echo_commons.shared.actors import ActorRef


async def finish_graph(app, graph_id, community, character):
    dispatcher = app.supervisor.workers["reflection-0"].dispatcher
    deadline = time.monotonic() + 600
    while time.monotonic() < deadline:
        with app.database.read() as connection:
            run = app.reflection.runs.get(connection, community, character, graph_id)
        if run.is_terminal:
            assert run.status == "completed", run
            return
        lease = await app.reflection_queue.claim(dispatcher.owner, utc_now())
        if lease is None:
            await asyncio.sleep(1)
        else:
            await dispatcher._execute(lease)
    raise TimeoutError("Core memory graph did not finish")


SCENARIOS = {
    "greeting": "晚上好，今天过得怎么样？",
    "recent_life": "最近生活里有什么让你惦记的事情？",
    "past_followup": "说说过去发生的一件你现在还记得的事吧。",
    "unfinished_promise": "现在有什么还没完成的约定，或者接下来想做的事情吗？",
    "closing": "今天先聊到这里，早点休息，下次见。",
}


def render_report(output):
    report = json.loads(output.read_text(encoding="utf-8"))
    lines = [
        "# 核心记忆与对话对照",
        "",
        "使用原数据库的只读备份进行真实模型验证，原数据库未修改。对照保持人物设定及提问相同。",
        "",
    ]
    labels = dict(
        zip(SCENARIOS, ("问候", "近期生活", "过去经历追问", "未完成约定", "结束聊天"), strict=True)
    )
    for item in report["characters"]:
        lines.extend(
            [
                f"## {item['character_id']}",
                "",
                f"正文长度：{len(item['before']['content'])} → "
                f"{len(item['after']['content'])} 字符。",
                f"核心重建调用：{item['model_requests']} 次；"
                f"未缓存输入 {item['input_tokens']}、输出 {item['output_tokens']} tokens（词元）。",
                "",
                "### 原核心记忆",
                "",
                item["before"]["content"] or "空白",
                "",
                "### 新核心记忆",
                "",
                item["after"]["content"] or "空白",
                "",
            ]
        )
        for before, after in zip(item["dialogue_before"], item["dialogue_after"], strict=True):
            assert before["scenario"] == after["scenario"] and before["input"] == after["input"]
            lines.extend(
                [
                    f"### {labels[before['scenario']]}",
                    "",
                    before["input"],
                    "",
                    "**重建前**",
                    "",
                    "\n\n".join(before["replies"]) or "角色保持沉默",
                    "",
                    "**重建后**",
                    "",
                    "\n\n".join(after["replies"]) or "角色保持沉默",
                    "",
                ]
            )
    output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")


async def compare_dialogue(app, character):
    dispatcher = app.supervisor.workers["conversations-0"].dispatcher
    results = []
    for scenario, text in SCENARIOS.items():
        conversation_id = str(uuid4())
        app.conversations.create(
            "night-diner",
            ConversationKind.DIRECT,
            (ActorRef("player", "lin"), ActorRef("character", character)),
            conversation_id=conversation_id,
            player_id="lin",
        )
        app.intake.send("night-diner", conversation_id, PlayerMessage("lin", str(uuid4()), text))
        deadline = time.monotonic() + 600
        while time.monotonic() < deadline:
            app.planner.plan()
            with app.database.read() as connection:
                turns = tuple(app.planner.social.list(connection, "night-diner", conversation_id))
                if turns and all(
                    turn.status.value in ("completed", "failed", "cancelled") for turn in turns
                ):
                    replies = connection.execute(
                        "SELECT text FROM messages WHERE conversation_id=? "
                        "AND sender_kind='character' "
                        "ORDER BY sequence",
                        (conversation_id,),
                    ).fetchall()
                    results.append(
                        dict(
                            scenario=scenario,
                            input=text,
                            replies=[row[0] for row in replies],
                            turn_statuses=[turn.status.value for turn in turns],
                        )
                    )
                    break
            lease = await app.queue.claim(dispatcher.owner, utc_now())
            if lease is None:
                await asyncio.sleep(1)
            else:
                await dispatcher._execute(lease)
        else:
            raise TimeoutError("Dialogue comparison did not finish")
        app.conversations.archive("night-diner", conversation_id)
        print(f"Dialogue finished: {character} / {scenario}", flush=True)
    return results


async def verify(database_path, output, compare=False):
    with tempfile.TemporaryDirectory(prefix="echo-core-memory-") as directory:
        target = Path(directory) / "verification.sqlite3"
        with (
            closing(sqlite3.connect(database_path.as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(target)) as destination,
        ):
            source.backup(destination)
        settings = load_settings().model_copy(
            update={
                "database_path": str(target),
                "worker_enabled": False,
                "log_path": str(Path(directory) / "verification.log"),
                "asset_directory": str(Path(directory) / "assets"),
                "quiet_window_seconds": 0,
            }
        )
        report = {"original_database_changed": False, "characters": []}
        async with application_lifecycle(settings) as app:
            with app.database.read() as connection:
                communities = connection.execute(
                    "SELECT community_id,state_version FROM communities "
                    "WHERE status='active' AND community_id<>'night-diner'"
                ).fetchall()
            for row in communities:
                app.communities.update(
                    row["community_id"],
                    expected_version=row["state_version"],
                    status=CommunityStatus.PAUSED,
                )
            if compare:
                for conversation in app.conversations.list("night-diner"):
                    if conversation.status.value == "active":
                        app.conversations.archive("night-diner", conversation.conversation_id)
            for character in ("xiaojin-main", "e4477e61-9989-4871-964d-103e6206a9ac"):
                before = app.memory_management.core_memory("night-diner", character)
                baseline_dialogue = await compare_dialogue(app, character) if compare else []
                with app.database.read() as connection:
                    first_event = connection.execute(
                        "SELECT COALESCE(MAX(event_id),0) FROM task_execution_events"
                    ).fetchone()[0]
                run = ViewScheduling(app.reflection).refresh_core(
                    "night-diner", character, str(uuid4())
                )
                print(f"Rebuilding {character}: {run.graph_run_id}", flush=True)
                await finish_graph(app, str(run.graph_run_id), "night-diner", character)
                after = app.memory_management.core_memory("night-diner", character)
                assert len(after["content"]) <= settings.reflection_core_memory_max_chars
                with app.database.read() as connection:
                    events = connection.execute(
                        "SELECT payload_json FROM task_execution_events WHERE event_id>? "
                        "AND event_kind='run_finished'",
                        (first_event,),
                    ).fetchall()
                    usage = [json.loads(row[0])["observation"]["usage_summary"] for row in events]
                report["characters"].append(
                    {
                        "character_id": character,
                        "before": before,
                        "after": after,
                        "model_requests": sum(item["model_request_count"] for item in usage),
                        "input_tokens": sum(item["input_tokens"] for item in usage),
                        "output_tokens": sum(item["output_tokens"] for item in usage),
                        "dialogue_before": baseline_dialogue,
                        "dialogue_after": await compare_dialogue(app, character) if compare else [],
                    }
                )
                output.parent.mkdir(parents=True, exist_ok=True)
                output.write_text(
                    json.dumps(report, ensure_ascii=False, indent=2), encoding="utf-8"
                )
                render_report(output)
                print(
                    f"Finished: {len(before['content'])} → {len(after['content'])} characters",
                    flush=True,
                )


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--compare", action="store_true")
    parser.add_argument(
        "--output", type=Path, default=Path("data/verification/u02-core-memory.json")
    )
    arguments = parser.parse_args()
    asyncio.run(verify(arguments.database.resolve(), arguments.output.resolve(), arguments.compare))
