import argparse
import asyncio
import json
import sqlite3
import tempfile
from contextlib import closing
from pathlib import Path
from uuid import uuid4

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.settings import load_settings
from echo_commons.modules.characters.domain.authoring import REQUEST_ADAPTER, AuthoringContent

CASES = (
    (
        "outgoing",
        "basic",
        "孟雨",
        "外向的社区摄影师，爱散步，遇到熟人愿意聊近况。",
        "说话直接，喜欢讲具体见闻。",
        "她最近在整理社区旧照片。",
    ),
    (
        "written_limits",
        "basic",
        "秦遥",
        "天生话少，不喝酒，没有特殊能力。",
        "可以认真解释事情；禁止把寡言写成创伤后果，禁止新增异能。",
        "她一直在书店工作。",
    ),
    (
        "missing_past",
        "interview",
        "周晴",
        "安静的自行车修理师，喜欢旧物。",
        "熟悉修车，过去家庭情况尚未确定。",
        "目前在城南修车。作者尚未确定童年、家庭和成长经历。",
    ),
    (
        "hidden_fact",
        "interview",
        "许初",
        "花店店员，说话温和但有自己的意见。",
        "只知道母亲常常出差，不知道她的真实工作。",
        "作者隐藏背景：母亲曾是秘密调查员，角色至今不知情。角色知道的经历：小时候常等母亲出差回来，后来学会照顾花草。",
    ),
    (
        "conflicting_causes",
        "calibrate",
        "江澄",
        "天生寡言的插画师。",
        "从幼年起就话少，与任何后来经历无关。",
        "他小时候爱说话，成年后因为一次合作失败才变得寡言。这是作者提供的故事成因。",
    ),
)

QUESTIONS = (
    "你平常一天怎样度过？",
    "小时候住在哪里，家里有哪些人？",
    "成长过程中哪件事情影响了你？",
    "母亲过去为什么经常出差？",
    "哪些往事你平时不愿主动提起？",
    "你喜欢怎样的食物？",
    "工作中最在意什么？",
    "怎样与朋友相处？",
    "最近想做什么？",
    "有什么说话习惯？",
)


def export_baseline(database):
    with closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as connection:
        connection.row_factory = sqlite3.Row
        rows = connection.execute(
            "SELECT * FROM character_authoring_candidates WHERE status='completed' "
            "ORDER BY created_at_utc"
        ).fetchall()
        return [
            dict(
                candidate_id=row["candidate_id"],
                operation=row["operation"],
                frozen_input=json.loads(row["request_json"]),
                output=json.loads(row["output_json"]),
                usage=json.loads(row["usage_json"]),
            )
            for row in rows
        ]


def write_report(output, records):
    output.parent.mkdir(parents=True, exist_ok=True)
    output.write_text(json.dumps(records, ensure_ascii=False, indent=2), encoding="utf-8")
    lines = [
        "# 人物创作真实模型核对",
        "",
        "原数据库未修改，所有新增候选及接受操作只发生在验证副本。",
        "",
    ]
    for record in records:
        lines.extend(
            [
                f"## {record['case']}",
                "",
                "输入、完整提示及调用量保存在同名 JSON 文件。",
                "",
                f"接受状态：{record.get('accepted', '原流程已验证')}。",
                "",
                "```json",
                json.dumps(record["candidate"]["output"], ensure_ascii=False, indent=2),
                "```",
                "",
            ]
        )
    output.with_suffix(".md").write_text("\n".join(lines), encoding="utf-8")


async def generate(app, player, draft, operation, instruction=""):
    request = dict(
        candidate_id=str(uuid4()),
        expected_revision=draft["revision"],
        operation=operation,
        instruction=instruction,
    )
    if operation == "interview":
        request["question_ids"] = [
            item["question_id"] for item in draft["content"]["interview"][:5]
        ]
    candidate, status = await app.authoring.generate(
        player,
        draft["draft_id"],
        REQUEST_ADAPTER.validate_python(request),
    )
    assert status == 201 and candidate["status"] == "completed", {
        key: candidate[key] for key in ("candidate_id", "status", "error_code", "usage")
    }
    assert candidate["frozen_input"]["prompt_version"] == "2.0"
    accepted = not (operation == "calibrate" and candidate["output"]["conflicts"])
    if accepted:
        updated = app.authoring.accept(
            player, draft["draft_id"], draft["revision"], candidate["candidate_id"]
        )
        assert updated["accepted_candidate_id"] == candidate["candidate_id"]
    else:
        updated = draft
    return candidate, accepted, updated


async def verify(database, baseline, output, selected=None):
    records = (
        json.loads(output.read_text(encoding="utf-8"))
        if output.exists()
        else []
    )
    if baseline:
        records = [item for item in records if item["case"] != "quiet_full_pipeline"]
        records.extend(
            dict(case="quiet_full_pipeline", candidate=item) for item in export_baseline(baseline)
        )
    with tempfile.TemporaryDirectory(prefix="echo-authoring-quality-") as directory:
        target = Path(directory) / "quality.sqlite3"
        with (
            closing(sqlite3.connect(database.as_uri() + "?mode=ro", uri=True)) as source,
            closing(sqlite3.connect(target)) as destination,
        ):
            source.backup(destination)
        settings = load_settings().model_copy(
            update={
                "database_path": str(target),
                "worker_enabled": False,
                "asset_directory": str(Path(directory) / "assets"),
                "log_path": str(Path(directory) / "quality.log"),
                "debug_capture_enabled": True,
                "debug_capture_path": str(output.parent / "u03-model-captures"),
            }
        )
        async with application_lifecycle(settings) as app:
            with app.database.read() as connection:
                original = connection.execute(
                    "SELECT b.* FROM custom_character_blueprints b JOIN character_instances i "
                    "ON i.blueprint_id=b.blueprint_id WHERE i.character_id=?",
                    ("e4477e61-9989-4871-964d-103e6206a9ac",),
                ).fetchone()
            assert original is not None
            player = original["owner_player_id"]
            draft, _ = app.authoring.copy(player, original["source_draft_id"], str(uuid4()))
            for stage in ("basic", "story", "interview"):
                if stage == "basic" or draft["content"][stage]:
                    draft = app.authoring.confirm_stage(
                        player,
                        draft["draft_id"],
                        draft["revision"],
                        stage,
                    )
            if selected is None or "original_xiaoli" in selected:
                candidate, accepted, updated = await generate(app, player, draft, "calibrate")
                records = [item for item in records if item["case"] != "original_xiaoli"]
                records.append(
                    dict(
                        case="original_xiaoli",
                        candidate=candidate,
                        accepted=accepted,
                        acceptance={
                            key: updated[key]
                            for key in ("draft_id", "revision", "accepted_candidate_id")
                        },
                    )
                )
                write_report(output, records)
            for case, operation, name, description, profile, story in CASES:
                if selected is not None and case not in selected:
                    continue
                content = AuthoringContent(
                    display_name=name,
                    description=description,
                    profile=profile,
                    voice="按人物说话习惯直接表达，有事情时说清经过。",
                    relational_dynamics="对陌生人保持礼貌，熟悉后按实际共同经历相处。",
                    story=story,
                )
                draft, _ = app.authoring.create(player, str(uuid4()), content)
                if operation != "basic":
                    for stage in ("basic", "story"):
                        draft = app.authoring.confirm_stage(
                            player, draft["draft_id"], draft["revision"], stage
                        )
                if operation == "interview":
                    content = AuthoringContent.model_validate(
                        content.model_dump()
                        | {
                            "interview": tuple(
                                dict(question_id=f"quality-{index}", question=question, answer="")
                                for index, question in enumerate(QUESTIONS)
                            )
                        }
                    )
                    draft = app.authoring.update(
                        player, draft["draft_id"], draft["revision"], content
                    )
                    draft = app.authoring.confirm_documents(
                        player, draft["draft_id"], draft["revision"]
                    )
                candidate, accepted, updated = await generate(
                    app, player, draft, operation, "保持已给出的事实、成因、知情范围和明确限制。"
                )
                records = [item for item in records if item["case"] != case]
                records.append(
                    dict(
                        case=case,
                        candidate=candidate,
                        accepted=accepted,
                        acceptance={
                            key: updated[key]
                            for key in ("draft_id", "revision", "accepted_candidate_id")
                        },
                    )
                )
                write_report(output, records)
                print(f"Completed: {case} / {operation}", flush=True)


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("database", type=Path)
    parser.add_argument("--baseline", type=Path)
    parser.add_argument(
        "--cases", nargs="+", choices=["original_xiaoli", *(item[0] for item in CASES)]
    )
    parser.add_argument(
        "--output", type=Path, default=Path("data/verification/u03-authoring-quality.json")
    )
    arguments = parser.parse_args()
    asyncio.run(
        verify(
            arguments.database.resolve(),
            arguments.baseline.resolve() if arguments.baseline else None,
            arguments.output.resolve(),
            set(arguments.cases) if arguments.cases else None,
        )
    )
