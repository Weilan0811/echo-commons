import json
import time
from concurrent.futures import ThreadPoolExecutor
from dataclasses import replace
from datetime import UTC, datetime, timedelta
from importlib.resources import files
from pathlib import Path
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from test_application_lifecycle import settings_for
from test_http_api import create_group

from echo_commons.app.main import create_app
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.mapping import utc_text
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.characters.domain.authoring import BasicRequest


def create_draft(client, name="林夏", **fields):
    body = {
        "player_id": "alice",
        "draft_id": str(uuid4()),
        "display_name": name,
        "description": "平时安静，熟悉以后喜欢开玩笑。玩游戏很认真，输了会嘴硬。",
        **fields,
    }
    response = client.post("/api/character-drafts", json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


def test_introduction_templates_preserve_handwriting_and_freeze_resources(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        draft, _ = create_draft(
            client,
            description="",
            introduction={
                "identity": {"age": "约二十岁", "occupation": "修理师", "gender": "自定义"},
                "daily_life": {"hobbies": [" 修理旧钟 ", "修理旧钟", ""]},
                "speech": {"examples": ["先让我看看。"]},
                "appearance": {"hair": "黑色短发"},
                "personality": {"stranger_style": "先听清对方的问题"},
            },
        )
        assert draft["content"]["description"] == "名字是林夏。"
        assert draft["content"]["introduction"]["daily_life"]["hobbies"] == ["修理旧钟"]
        original = draft["content"]["profile"]
        preview = action(client, draft, "documents/template")
        assert preview["input_revision"] == draft["revision"]
        output = preview["output"]
        assert "黑色短发" in output["profile"] and "修理旧钟" in output["profile"]
        assert "先让我看看。" in output["voice"]
        assert "先听清对方的问题" in output["relational_dynamics"]
        assert "修理旧钟" not in output["voice"]
        url = f"/api/character-drafts/{draft['draft_id']}"
        assert (
            client.get(url, params={"player_id": "alice"}).json()["content"]["profile"] == original
        )
        accepted = action(client, draft, "documents/template/accept")
        assert accepted["content"]["introduction"] == draft["content"]["introduction"]
        assert (
            client.post(
                url + "/documents/template/accept",
                json={"player_id": "alice", "expected_revision": draft["revision"]},
            ).status_code
            == 409
        )
        blueprint, _ = confirm(client, accepted)
        copied = client.post(
            url + "/copy", json={"player_id": "alice", "draft_id": str(uuid4())}
        ).json()
        assert copied["content"] == blueprint["content"]
        changed = copied["content"] | {"introduction": {"identity": {"age": "二十一岁"}}}
        saved = client.put(
            f"/api/character-drafts/{copied['draft_id']}",
            json={
                "player_id": "alice",
                "expected_revision": copied["revision"],
                "content": changed,
            },
        ).json()
        assert saved["content"]["profile"] == accepted["content"]["profile"]
        assert saved["workflow"]["documents_review"] == "review_required"
        assert (
            client.get(
                f"/api/custom-blueprints/{blueprint['blueprint_id']}", params={"player_id": "alice"}
            ).json()["content"]
            == blueprint["content"]
        )
        application = client.app.state.application
        with application.database.read() as connection:
            resource = application.characters.catalog.get(connection, blueprint["blueprint_id"])
            assert resource.profile.content == accepted["content"]["profile"]
            assert (
                application.characters.catalog.author_materials(
                    connection, blueprint["blueprint_id"], resource.content_version
                )
                == ()
            )


@pytest.mark.parametrize(
    "introduction",
    [
        {"identity": {"age": "x" * 81}},
        {"daily_life": {"hobbies": ["a"] * 11}},
        {"speech": {"examples": ["a"] * 4}},
        {"appearance": {"hair": "x" * 501}},
        {
            "daily_life": {
                key: [str(i) + "x" * 197 for i in range(10)]
                for key in ("hobbies", "likes", "dislikes", "habits", "skills")
            }
        },
    ],
)
def test_introduction_actual_limits(tmp_path, introduction):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        response = client.post(
            "/api/character-drafts",
            json={
                "player_id": "alice",
                "draft_id": str(uuid4()),
                "display_name": "林夏",
                "introduction": introduction,
            },
        )
        assert response.status_code == 422, response.text


def test_introduction_is_counted_in_material_budget_and_image_prompt(tmp_path):
    from echo_commons.modules.assets.contracts import GenerationRequest

    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        draft, _ = create_draft(client, introduction={"appearance": {"hair": "黑色短发"}})
        application = client.app.state.application
        with application.database.read() as connection:
            prompt = application.image_generations.prompt(
                GenerationRequest(
                    player_id="alice",
                    client_request_id="intro-prompt",
                    purpose="character_illustration",
                    style_id="watercolor",
                    draft_id=draft["draft_id"],
                    revision=draft["revision"],
                    appearance="站在窗边",
                ),
                connection,
            )
        assert "人物外貌事实：\n发型与发色：黑色短发" in prompt
        assert "本次姿态和场景补充：\n站在窗边" in prompt
        body = draft["content"] | {
            "description": "x" * 8000,
            "story": "s" * 24000,
            "interview": [
                {"question_id": str(i), "question": "q" * 500, "answer": "a" * 1500}
                for i in range(4)
            ],
        }
        response = client.put(
            f"/api/character-drafts/{draft['draft_id']}",
            json={"player_id": "alice", "expected_revision": draft["revision"], "content": body},
        )
        assert response.status_code == 422, response.text


def test_introduction_full_budget_fits_template_labels():
    from echo_commons.modules.characters.domain.authoring import AuthoringContent, Introduction
    from echo_commons.modules.characters.templates.authoring import (
        default_content,
        introduction_documents,
    )

    introduction = Introduction.model_validate(
        {
            "daily_life": {
                key: [str(i) + "x" * 199 for i in range(10)]
                for key in ("hobbies", "likes", "dislikes", "habits")
            }
        }
    )
    assert introduction.character_count() == 8000
    content = AuthoringContent.model_validate(
        default_content("林" * 80, "").model_dump() | {"introduction": introduction}
    )
    output = introduction_documents(content)
    assert 8000 < len(output.profile) <= 9000
    assert all(text in output.profile for _, _, text in introduction.source_fields())


@pytest.mark.model
def test_real_introduction_inspiration_and_calibration(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        draft, _ = create_draft(
            client,
            introduction={
                "identity": {"age": "约二十岁", "occupation": "修理师"},
                "daily_life": {"hobbies": ["修理旧钟"]},
                "appearance": {"hair": "黑色短发"},
                "speech": {"examples": ["先让我看看。"]},
            },
        )
        url = f"/api/character-drafts/{draft['draft_id']}"
        response = client.post(
            url + "/candidates",
            json={
                "player_id": "alice",
                "expected_revision": draft["revision"],
                "candidate_id": str(uuid4()),
                "operation": "basic",
                "instruction": "保留自介资料中的所有事实，人物档案开头交代基本资料。",
            },
        )
        assert response.status_code == 201, response.text
        candidate = response.json()
        assert (
            candidate["frozen_input"]["content"]["introduction"] == draft["content"]["introduction"]
        )
        assert "黑" in candidate["output"]["profile"]
        assert candidate["usage"]["total_tokens"] > 0
        draft = action(client, draft, f"candidates/{candidate['candidate_id']}/accept")
        draft = action(client, draft, "stages/basic/confirm")
        response = client.put(
            url,
            json={
                "player_id": "alice",
                "expected_revision": draft["revision"],
                "content": draft["content"] | {"profile": "林夏的头发是银色长发。"},
            },
        )
        assert response.status_code == 200, response.text
        draft = action(client, response.json(), "stages/basic/confirm")
        response = client.post(
            url + "/candidates",
            json={
                "player_id": "alice",
                "expected_revision": draft["revision"],
                "candidate_id": str(uuid4()),
                "operation": "calibrate",
            },
        )
        assert response.status_code == 201, response.text
        calibration = response.json()
        assert calibration["output"]["conflicts"], calibration
        refs = {ref for item in calibration["output"]["conflicts"] for ref in item["source_refs"]}
        assert "introduction:appearance.hair" in refs and "profile" in refs
        rejected = client.post(
            url + f"/candidates/{calibration['candidate_id']}/accept",
            json={"player_id": "alice", "expected_revision": draft["revision"]},
        )
        assert rejected.status_code == 409
        assert client.get(url, params={"player_id": "alice"}).json()["content"] == draft["content"]
        print("INTRODUCTION_INSPIRATION", json.dumps(candidate, ensure_ascii=False))
        print("INTRODUCTION_CALIBRATION", json.dumps(calibration, ensure_ascii=False))


def action(client, draft, path, **fields):
    response = client.post(
        f"/api/character-drafts/{draft['draft_id']}/{path}",
        json={"player_id": "alice", "expected_revision": draft["revision"], **fields},
    )
    assert response.status_code == 200, response.text
    return response.json()


def confirm(client, draft):
    for stage in ("basic", "story", "interview"):
        present = stage == "basic" or bool(draft["content"][stage])
        if present and draft["workflow"][stage] != "accepted":
            draft = action(client, draft, f"stages/{stage}/confirm")
    if draft["workflow"]["documents_review"] != "accepted":
        draft = action(client, draft, "documents/confirm", acknowledge_documents_match=True)
    body = {
        "player_id": "alice",
        "expected_revision": draft["revision"],
        "acknowledge_fixed_background": True,
    }
    response = client.post(f"/api/character-drafts/{draft['draft_id']}/confirm", json=body)
    assert response.status_code == 201, response.text
    return response.json(), body


def test_manual_creation_scope_immutability_copy_and_restart(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    with TestClient(create_app(settings)) as client:
        create_group(client)
        template = client.get("/api/character-authoring/template").json()
        assert template["interview"] and template["fixed_background_notice"]
        original, request = create_draft(client)
        url = f"/api/character-drafts/{original['draft_id']}"
        assert client.get(url, params={"player_id": "bob"}).status_code == 404
        assert client.post("/api/character-drafts", json=request).status_code == 200
        conflict = client.post(
            "/api/character-drafts", json=request | {"description": "另一个人物"}
        )
        assert conflict.status_code == 409
        content = original["content"] | {"voice": "我说话简短，偶尔有干幽默。"}
        body = {"player_id": "alice", "expected_revision": 1, "content": content}
        updated = client.put(url, json=body)
        assert updated.status_code == 200, updated.text
        assert updated.json()["revision"] == 2
        assert client.put(url, json=body).json()["error"]["code"] == "draft_revision_conflict"
        assert client.post("/api/character-drafts", json=request).json()["revision"] == 2
        blueprint, confirmation = confirm(client, updated.json())
        assert client.post(url + "/confirm", json=confirmation).status_code == 200
        assert client.put(
            url, json=body | {"expected_revision": confirmation["expected_revision"]}
        ).json()["error"]["code"] == ("blueprint_immutable")
        assert (
            client.post(
                url + "/confirm",
                json=confirmation
                | {
                    "acknowledge_fixed_background": False,
                },
            ).status_code
            == 422
        )
        blueprint_id = blueprint["blueprint_id"]
        assert (
            client.get(
                f"/api/custom-blueprints/{blueprint_id}",
                params={
                    "player_id": "bob",
                },
            ).status_code
            == 404
        )
        for character_id in ("custom-one", "custom-two"):
            response = client.post(
                "/api/communities/community/characters",
                json={
                    "player_id": "alice",
                    "blueprint_id": blueprint_id,
                    "character_id": character_id,
                },
            )
            assert response.status_code == 201, response.text
            assert response.json()["display_name"] == "林夏"
            assert "content" not in response.json()
        assert (
            client.post(
                "/api/communities/community/characters",
                json={
                    "player_id": "bob",
                    "blueprint_id": blueprint_id,
                },
            ).status_code
            == 404
        )
        public = client.get("/api/blueprints").json()
        assert blueprint_id not in {item["blueprint_id"] for item in public}
        copied_id = str(uuid4())
        copied = client.post(url + "/copy", json={"player_id": "alice", "draft_id": copied_id})
        assert copied.status_code == 201
        assert copied.json()["status"] == "draft" and copied.json()["revision"] == 1
        assert copied.json()["confirmed_blueprint_id"] is None
        assert (
            client.post(
                url + "/copy",
                json={
                    "player_id": "alice",
                    "draft_id": copied_id,
                },
            ).status_code
            == 200
        )
        with client.app.state.application.database.read() as connection:
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM memory_entries WHERE character_id IN (?,?)",
                    ("custom-one", "custom-two"),
                ).fetchone()[0]
                == 0
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM character_state_entries WHERE character_id IN (?,?)",
                    ("custom-one", "custom-two"),
                ).fetchone()[0]
                == 6
            )
    with TestClient(create_app(settings)) as client:
        assert (
            client.get(
                f"/api/custom-blueprints/{blueprint_id}",
                params={
                    "player_id": "alice",
                },
            ).json()["content"]
            == content
        )
        members = client.get(
            "/api/communities/community/characters",
            params={
                "player_id": "bob",
            },
        ).json()
        assert {item["character_id"] for item in members} >= {"custom-one", "custom-two"}


def test_material_limits_and_scoped_pagination(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        draft, body = create_draft(client)
        long_body = body | {"draft_id": str(uuid4()), "story": "故事" * 5000}
        rejected = client.post("/api/character-drafts", json=long_body)
        assert rejected.status_code == 201
        assert long_body["story"] not in rejected.json()["content"]["profile"]
        response = client.post(
            "/api/character-drafts",
            json=long_body | {"draft_id": str(uuid4()), "profile": "人物正文"},
        )
        assert response.status_code == 201
        assert response.json()["content"]["story"] == long_body["story"]
        create_draft(client, "阿乐")
        first = client.get(
            "/api/character-drafts", params={"player_id": "alice", "limit": 1}
        ).json()
        assert len(first["items"]) == 1 and first["has_more"]
        second = client.get(
            "/api/character-drafts",
            params={
                "player_id": "alice",
                "limit": 1,
                "cursor": first["cursor"],
            },
        ).json()
        assert first["items"][0]["draft_id"] != second["items"][0]["draft_id"]
        assert (
            client.get(
                "/api/character-drafts",
                params={
                    "player_id": "bob",
                    "cursor": first["cursor"],
                },
            ).status_code
            == 400
        )
        assert (
            client.get(
                "/api/custom-blueprints",
                params={
                    "player_id": "alice",
                    "cursor": first["cursor"],
                },
            ).status_code
            == 400
        )
        assert (
            client.post(
                "/api/character-drafts",
                json=body
                | {
                    "draft_id": str(uuid4()),
                    "capabilities": ["modify_database"],
                },
            ).status_code
            == 422
        )
        assert (
            client.post(
                "/api/character-drafts",
                json=body
                | {
                    "draft_id": str(uuid4()),
                    "display_name": "   ",
                },
            ).status_code
            == 400
        )
        assert draft["material_processing"] == "stored_only"


def test_interrupted_candidate_query_does_not_restart_and_stale_cannot_be_saved(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        draft, _ = create_draft(client)
        application = client.app.state.application
        request = BasicRequest(candidate_id=uuid4(), expected_revision=1, operation="basic")
        row, _, _, _ = application.authoring.start_candidate("alice", draft["draft_id"], request)
        with application.database.transaction() as connection:
            connection.execute(
                "UPDATE character_authoring_candidates SET deadline_utc=? WHERE candidate_id=?",
                (utc_text(datetime.now(UTC) - timedelta(seconds=1)), row["candidate_id"]),
            )
        url = f"/api/character-drafts/{draft['draft_id']}"
        candidate = client.get(
            url + "/candidates/" + row["candidate_id"],
            params={
                "player_id": "alice",
            },
        ).json()
        assert candidate["status"] == "failed"
        assert "error_code" not in candidate
        managed = client.get("/internal/players/alice/character-candidates")
        assert managed.status_code == 200
        assert managed.json()["items"][0]["error_code"] == "authoring_interrupted"
        assert client.get("/internal/players/alice/image-generations").json()["items"] == []
        assert client.get("/internal/players/unknown/image-generations").status_code == 404
        repeat = client.post(
            url + "/candidates",
            json=request.model_dump(mode="json")
            | {
                "player_id": "alice",
            },
        )
        assert repeat.status_code == 200 and repeat.json()["status"] == "failed"
        assert application.gateway._clients == {}
        saved = client.post(
            url + "/candidates/" + row["candidate_id"] + "/accept",
            json={
                "player_id": "alice",
                "expected_revision": 1,
            },
        )
        assert saved.status_code == 409 and saved.json()["error"]["code"] == "candidate_stale"
        assert client.get(url, params={"player_id": "alice"}).json()["revision"] == 1


def test_version_four_upgrade_preserves_real_records(tmp_path):
    sql = tmp_path / "version4"
    sql.mkdir()
    for source in files("echo_commons.infrastructure.database.sql").iterdir():
        if source.name.endswith(".sql") and int(source.name[:4]) <= 4:
            (sql / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    database = Database(tmp_path / "upgrade.sqlite3")
    assert initialize(database, sql_directory=sql) == 4
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO players VALUES (?,?,?)",
            (
                "original",
                "原始玩家",
                utc_text(datetime.now(UTC)),
            ),
        )
    with database.read() as connection:
        before = tuple(connection.execute("SELECT * FROM players").fetchone())
    # 旧版本数据按旧结构保存，不能使用要求新字段的当前创建入口。
    now = utc_text(datetime.now(UTC))
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO communities (community_id,name,timezone,world_time_utc,"
            "created_at_utc,updated_at_utc) VALUES ('original-community','原社群','UTC',?,?,?)",
            (now, now, now),
        )
        connection.execute(
            "INSERT INTO character_instances (character_id,community_id,blueprint_id,"
            "blueprint_version,created_at_utc,updated_at_utc) "
            "VALUES ('original-character','original-community','xiaojin','0.1.0',?,?)",
            (now, now),
        )
    tables = ("players", "communities", "character_instances")
    with database.read() as connection:
        records = {
            table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
            for table in tables
        }
    assert initialize(database) == initialize(database) == 15
    with database.read() as connection:
        assert tuple(connection.execute("SELECT * FROM players").fetchone()) == before
        for table in tables:
            current = [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
            if table == "character_instances":
                assert [row[:-4] for row in current] == records[table]
                assert all(row[-4:] == ("full", "ready", None, 0) for row in current)
            elif table == "communities":
                assert [row[:-2] for row in current] == records[table]
                assert all(row[-2:] == (None, None) for row in current)
            else:
                assert current == records[table]
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_missing_credentials_preserves_draft_and_persisted_failure(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        draft, _ = create_draft(client)
        application = client.app.state.application
        # 使用真实网关及缺失凭据配置，验证正式失败路径，不产生替代响应。
        application.gateway.registry = replace(application.models, credentials={})
        url = f"/api/character-drafts/{draft['draft_id']}"
        request = {
            "player_id": "alice",
            "candidate_id": str(uuid4()),
            "expected_revision": 1,
            "operation": "basic",
        }
        failed = client.post(url + "/candidates", json=request)
        assert failed.status_code == 503, failed.text
        assert failed.json()["error"]["code"] == "authoring_model_unavailable"
        assert failed.json()["candidate_id"] == request["candidate_id"]
        stored = client.get(
            url + "/candidates/" + request["candidate_id"],
            params={
                "player_id": "alice",
            },
        ).json()
        assert stored["status"] == "failed" and stored["output"] is None
        assert stored["usage"]["provider_request_count"] == 0
        assert client.post(url + "/candidates", json=request).json() == stored
        assert client.get(url, params={"player_id": "alice"}).json() == draft
        assert (
            client.post(
                url + "/candidates",
                json=request | {"operation": "basic", "instruction": "different"},
            ).status_code
            == 409
        )
        assert application.gateway._clients == {}


def wait_turn(client, conversation, *, after=None):
    deadline = time.monotonic() + 150
    while time.monotonic() < deadline:
        turns = client.get(
            f"/api/conversations/{conversation}/turns",
            params={
                "player_id": "alice",
            },
        ).json()
        if turns and turns[-1]["status"] == "completed" and turns[-1]["social_turn_id"] != after:
            assert all(
                item["status"] == "completed"
                for item in turns[-1]["participation"]
                if item["status"] != "silent"
            ), turns
            return turns[-1]
        time.sleep(0.1)
    pytest.fail("Real model conversation did not complete")


@pytest.mark.model
def test_real_authoring_four_operations_and_custom_characters_chat(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=True))) as client:
        create_group(client)
        draft, _ = create_draft(client, story="小时候在海边住过，每周末跟外婆一起散步。")
        url = f"/api/character-drafts/{draft['draft_id']}"
        template = client.get("/api/character-authoring/template").json()
        questions = [
            {"question_id": item["id"], "question": item["question"], "answer": ""}
            for item in template["interview"][:10]
        ]

        def generate(operation, **extra):
            nonlocal draft
            body = {
                "player_id": "alice",
                "candidate_id": str(uuid4()),
                "expected_revision": draft["revision"],
                "operation": operation,
                **extra,
            }
            generated = client.post(url + "/candidates", json=body)
            assert generated.status_code == 201, generated.text
            candidate = generated.json()
            assert candidate["status"] == "completed" and candidate["usage"]["total_tokens"] > 0
            assert (
                client.get(url, params={"player_id": "alice"}).json()["content"] == draft["content"]
            )
            assert client.post(url + "/candidates", json=body).json() == candidate
            draft = action(client, draft, "candidates/" + candidate["candidate_id"] + "/accept")
            repeated = action(client, draft, "candidates/" + candidate["candidate_id"] + "/accept")
            assert repeated == draft
            return candidate

        generate("basic", instruction="保持原性格和明确要求。")
        draft = action(client, draft, "stages/basic/confirm")
        generate("story", instruction="保留海边与外婆散步，简短完善故事。")
        draft = action(client, draft, "stages/story/confirm")
        generate("calibrate")
        saved = client.put(
            url,
            json={
                "player_id": "alice",
                "expected_revision": draft["revision"],
                "content": draft["content"] | {"interview": questions},
            },
        )
        assert saved.status_code == 200, saved.text
        draft = saved.json()
        # 选题尚未产生回答，作者可以先审核当前正文再开始采访。
        draft = action(client, draft, "documents/confirm", acknowledge_documents_match=True)
        bases = []
        for offset in (0, 4, 8):
            candidate = generate(
                "interview",
                question_ids=[item["question_id"] for item in questions[offset : offset + 4]],
            )
            bases.append(candidate["frozen_input"]["interview_basis"])
            print("INTERVIEW", json.dumps(candidate["output"], ensure_ascii=False))
        assert bases[0] == bases[1] == bases[2]
        draft = action(client, draft, "stages/interview/confirm")
        calibration = generate("calibrate")
        print("CALIBRATION", json.dumps(calibration["output"], ensure_ascii=False))
        ai_blueprint, _ = confirm(client, draft)
        manual, _ = create_draft(client, "阿乐", description="喜欢下棋，乐观，说话直接。")
        manual_blueprint, _ = confirm(client, manual)
        for character, blueprint in (
            ("ai-custom", ai_blueprint),
            ("manual-custom", manual_blueprint),
        ):
            assert (
                client.post(
                    "/api/communities/community/characters",
                    json={
                        "player_id": "alice",
                        "character_id": character,
                        "blueprint_id": blueprint["blueprint_id"],
                    },
                ).status_code
                == 201
            )
        for conversation, kind, characters in (
            ("custom-direct", "direct", ["ai-custom"]),
            ("custom-group", "group", ["ai-custom", "manual-custom"]),
        ):
            created = client.post(
                "/api/communities/community/conversations",
                json={
                    "player_id": "alice",
                    "conversation_id": conversation,
                    "kind": kind,
                    "actors": [{"kind": "player", "actor_id": "alice"}]
                    + [{"kind": "character", "actor_id": key} for key in characters],
                },
            )
            assert created.status_code == 201, created.text
            assert (
                client.post(
                    f"/api/conversations/{conversation}/messages",
                    json={
                        "player_id": "alice",
                        "client_message_id": conversation,
                        "text": "一起玩棋盘游戏怎么样？说说你现在的想法。",
                    },
                ).status_code
                == 202
            )
            wait_turn(client, conversation)
        with client.app.state.application.database.read() as connection:
            snapshots = [
                json.loads(row[0])
                for row in connection.execute(
                    "SELECT snapshot_json FROM conversation_tasks WHERE character_id='ai-custom'",
                )
            ]
            assert snapshots
            assert all(item["self"]["profile"] == draft["content"]["profile"] for item in snapshots)
            assert all(item["self"]["blueprint_version"] == "0.1.0" for item in snapshots)


@pytest.mark.model
def test_real_generation_allows_write_and_rejects_stale_candidate(tmp_path):
    settings = settings_for(tmp_path, workers=True).model_copy(update={"model_concurrency": 1})
    with TestClient(create_app(settings)) as client:
        create_group(client)
        draft, _ = create_draft(client)
        url = f"/api/character-drafts/{draft['draft_id']}"
        candidate_id = str(uuid4())
        body = {
            "player_id": "alice",
            "candidate_id": candidate_id,
            "expected_revision": 1,
            "operation": "basic",
            "instruction": "根据性格补充一段过去故事并整理完整人物正文。",
        }
        with ThreadPoolExecutor(max_workers=1) as executor:
            future = executor.submit(client.post, url + "/candidates", json=body)
            deadline = time.monotonic() + 15
            while time.monotonic() < deadline:
                with client.app.state.application.database.read() as connection:
                    row = connection.execute(
                        "SELECT status FROM character_authoring_candidates WHERE candidate_id=?",
                        (candidate_id,),
                    ).fetchone()
                if row:
                    assert row[0] == "processing"
                    break
                time.sleep(0.05)
            else:
                pytest.fail("Authoring input was not persisted")
            content = draft["content"] | {"voice": "说话直接，今天明确采用这一条。"}
            updated = client.put(
                url, json={"player_id": "alice", "expected_revision": 1, "content": content}
            )
            assert updated.status_code == 200, updated.text
            sent = client.post(
                "/api/conversations/conversation/messages",
                json={
                    "player_id": "alice",
                    "client_message_id": "during-authoring",
                    "text": "两位小槿，说说今天想玩什么游戏。",
                },
            )
            assert sent.status_code == 202, sent.text
            generated = future.result(timeout=100)
        assert generated.status_code == 201, generated.text
        rejected = client.post(
            url + "/candidates/" + candidate_id + "/accept",
            json={
                "player_id": "alice",
                "expected_revision": 2,
            },
        )
        assert rejected.status_code == 409 and rejected.json()["error"]["code"] == "candidate_stale"
        assert client.get(url, params={"player_id": "alice"}).json()["content"] == content
        wait_turn(client, "conversation")
    # 同时安排真实创作与聊天，用供应商开始和结束记录检查共同并发额度。
    events = [json.loads(line) for line in Path(settings.log_path).read_text().splitlines()]
    active = 0
    authors, characters = 0, 0
    for event in events:
        if event["event"] == "model.call.started":
            active += 1
            assert active == 1
            if event.get("agent_id", "").startswith("author:"):
                authors += 1
            else:
                characters += 1
        elif event["event"] in {"model.call.completed", "model.call.failed", "model.call.invalid"}:
            active -= 1
            assert active == 0
    assert active == 0 and authors >= 1 and characters >= 1
