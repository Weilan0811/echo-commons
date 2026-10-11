import time
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from pydantic import ValidationError
from test_application_lifecycle import settings_for
from test_character_authoring import action, confirm, create_draft
from test_http_api import create_group

from echo_commons.agents.authoring import validate_candidate
from echo_commons.app.main import create_app
from echo_commons.modules.characters.domain.authoring import (
    AuthoringContent,
    BasicRequest,
    CalibrateRequest,
    InterviewRequest,
    StoryRequest,
    merge_candidate,
)


def save(client, draft, **changes):
    response = client.put(
        f"/api/character-drafts/{draft['draft_id']}",
        json={
            "player_id": "alice",
            "expected_revision": draft["revision"],
            "content": draft["content"] | changes,
        },
    )
    assert response.status_code == 200, response.text
    return response.json()


def selected(client, count=10, answer=""):
    return [
        dict(question_id=item["id"], question=item["question"], answer=answer)
        for item in client.get("/api/character-authoring/template").json()["interview"][:count]
    ]


def post(client, draft, path, **extra):
    return client.post(
        f"/api/character-drafts/{draft['draft_id']}/{path}",
        json={
            "player_id": "alice",
            "expected_revision": draft["revision"],
            **extra,
        },
    )


def test_ordered_manual_workflow_review_and_optional_stages(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        draft, _ = create_draft(client, story="幼年在海边生活。", interview=selected(client))
        assert "海边" not in draft["content"]["profile"]
        response = post(client, draft, "candidates", candidate_id=str(uuid4()), operation="story")
        assert (
            response.status_code == 409
            and response.json()["error"]["code"] == "stage_dependency_unmet"
        )
        assert post(client, draft, "stages/story/confirm").status_code == 409
        assert post(client, draft, "confirm", acknowledge_fixed_background=True).status_code == 409
        draft = action(client, draft, "stages/basic/confirm")
        assert action(client, draft, "stages/basic/confirm") == draft
        assert (
            post(
                client,
                draft,
                "candidates",
                candidate_id=str(uuid4()),
                operation="interview",
                question_ids=["daily_rhythm"],
            ).status_code
            == 409
        )
        draft = action(client, draft, "stages/story/confirm")
        response = post(client, draft, "stages/interview/confirm")
        assert response.json()["error"]["code"] == "interview_incomplete"
        draft = save(client, draft, interview=selected(client, answer="我暂时不想回答。"))
        assert draft["workflow"]["basic"] == "accepted"
        assert draft["workflow"]["documents_review"] == "review_required"
        assert action(client, draft, "stages/basic/confirm") == draft
        draft = action(client, draft, "stages/interview/confirm")
        response = post(client, draft, "confirm", acknowledge_fixed_background=True)
        assert response.json()["error"]["code"] == "documents_review_required"
        draft = action(client, draft, "documents/confirm", acknowledge_documents_match=True)
        revision = draft["revision"]
        assert save(client, draft)["revision"] == revision
        draft = save(client, draft, avatar_url="https://example.com/avatar.png")
        assert draft["workflow"]["interview"] == "accepted"
        draft = save(client, draft, display_name="新名字")
        assert draft["workflow"]["interview"] == "accepted"
        assert draft["workflow"]["documents_review"] == "review_required"
        draft = action(client, draft, "documents/confirm", acknowledge_documents_match=True)
        original_answers = draft["content"]["interview"]
        draft = save(client, draft, profile=draft["content"]["profile"] + "\n喜欢慢慢说话。")
        assert all(
            draft["workflow"][stage] == "review_required"
            for stage in ("basic", "story", "interview")
        )
        assert draft["content"]["interview"] == original_answers
        draft = action(client, draft, "stages/basic/confirm")
        draft = action(client, draft, "stages/story/confirm")
        draft = action(client, draft, "stages/interview/confirm")
        blueprint, _ = confirm(client, draft)
        copied = client.post(
            f"/api/character-drafts/{draft['draft_id']}/copy",
            json={"player_id": "alice", "draft_id": str(uuid4())},
        ).json()
        assert copied["workflow"]["basic"] == "pending"
        assert copied["workflow"]["story"] == copied["workflow"]["interview"] == "review_required"
        assert copied["content"] == blueprint["content"]
        # 作者可以明确删除整份未完成采访，在故事阶段结束。
        partial, _ = create_draft(client, story="海边生活。", interview=selected(client))
        partial = action(client, partial, "stages/basic/confirm")
        partial = action(client, partial, "stages/story/confirm")
        partial = save(client, partial, interview=[])
        assert partial["workflow"]["interview"] == "unused"
        confirm(client, partial)


def test_interview_selection_boundaries_basis_invalidation_and_snapshot(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        application = client.app.state.application
        draft, _ = create_draft(client, story="明确经历。", interview=selected(client, count=9))
        draft = action(client, draft, "stages/basic/confirm")
        draft = action(client, draft, "stages/story/confirm")
        response = post(
            client,
            draft,
            "candidates",
            candidate_id=str(uuid4()),
            operation="interview",
            question_ids=["daily_rhythm"],
        )
        assert (
            response.status_code == 409
            and response.json()["error"]["code"] == "interview_incomplete"
        )
        draft = save(client, draft, interview=selected(client, count=15))
        draft = action(client, draft, "documents/confirm", acknowledge_documents_match=True)
        for ids in (
            ["unknown"],
            ["daily_rhythm"] * 2,
            [item["question_id"] for item in draft["content"]["interview"][:6]],
        ):
            assert post(
                client,
                draft,
                "candidates",
                candidate_id=str(uuid4()),
                operation="interview",
                question_ids=ids,
            ).status_code in (400, 422)
        request = InterviewRequest(
            candidate_id=uuid4(),
            expected_revision=draft["revision"],
            operation="interview",
            question_ids=("daily_rhythm",),
        )
        row, _, _, _ = application.authoring.start_candidate("alice", draft["draft_id"], request)
        stored = application.authoring.candidate("alice", draft["draft_id"], row["candidate_id"])
        basis = stored["frozen_input"]["interview_basis"]
        assert basis["profile"] == draft["content"]["profile"]
        assert basis["story"] == draft["content"]["story"]
        assert basis["agent_contract"] == application.authoring.agent.prompts["interview"]
        assert basis["expression_guidance"] == ""
        current = application.authoring.get("alice", draft["draft_id"])
        assert current["workflow"]["interview_basis"] == basis
        current = save(client, current, story="作者重新写了过去。")
        assert current["workflow"]["interview_basis"] is None
        assert current["workflow"]["story"] == "review_required"
        assert current["content"]["interview"] == draft["content"]["interview"]
        assert stored["frozen_input"]["interview_basis"] == basis
        assert (
            post(
                client,
                current,
                "candidates",
                candidate_id=str(uuid4()),
                operation="interview",
                question_ids=["daily_rhythm"],
            ).status_code
            == 409
        )
        duplicate = draft["content"]["interview"][:1] * 10
        assert (
            client.put(
                f"/api/character-drafts/{draft['draft_id']}",
                json={
                    "player_id": "alice",
                    "expected_revision": current["revision"],
                    "content": current["content"] | {"interview": duplicate},
                },
            ).status_code
            == 422
        )


def test_typed_operations_preserve_material_and_validate_sources():
    content = AuthoringContent(
        display_name="甲",
        description="认真",
        profile="身份",
        voice="简洁",
        relational_dynamics="保留边界",
        story="作者故事",
        interview=tuple(
            dict(question_id=str(i), question=f"问题{i}", answer="旧回答") for i in range(10)
        ),
    )
    common = dict(candidate_id=uuid4(), expected_revision=1)
    basic = validate_candidate(
        dict(
            operation="basic",
            description="认真而温和",
            profile="新身份",
            voice="新表达",
            relational_dynamics="新边界",
            changes=[],
        ),
        content,
        BasicRequest(**common, operation="basic"),
    )
    assert merge_candidate(content, basic).story == content.story
    story = validate_candidate(
        dict(operation="story", story="完善故事", changes=[]),
        content,
        StoryRequest(**common, operation="story"),
    )
    assert merge_candidate(content, story).profile == content.profile
    interview = validate_candidate(
        dict(
            operation="interview",
            answers=[dict(question_id="0", answer="新回答")],
            new_background_suggestions=["供作者选择的过去建议"],
        ),
        content,
        InterviewRequest(**common, operation="interview", question_ids=("0",)),
    )
    merged = merge_candidate(content, interview)
    assert merged.interview[0].question == content.interview[0].question
    assert merged.interview[1:] == content.interview[1:]
    assert merged.story == content.story
    calibration = dict(
        operation="calibrate",
        profile="校准身份",
        voice="校准表达",
        relational_dynamics="校准边界",
        changes=[dict(document="profile", explanation="依据作者故事", source_refs=["story"])],
        conflicts=[],
    )
    request = CalibrateRequest(**common, operation="calibrate")
    result = merge_candidate(content, validate_candidate(calibration, content, request))
    assert result.story == content.story and result.interview == content.interview
    with pytest.raises(ValueError):
        validate_candidate(
            calibration
            | {
                "changes": [
                    dict(
                        document="voice", explanation="未知来源", source_refs=["interview:unknown"]
                    )
                ]
            },
            content,
            request,
        )
    with pytest.raises(ValidationError):
        validate_candidate(calibration | {"story": "越界修改"}, content, request)
    with pytest.raises(ValueError):
        validate_candidate(
            dict(
                operation="interview",
                answers=[dict(question_id="1", answer="越界")],
                new_background_suggestions=[],
            ),
            content,
            InterviewRequest(**common, operation="interview", question_ids=("0",)),
        )


@pytest.mark.model
def test_real_interview_voice_situations_and_explicit_conflict(tmp_path):
    from test_character_authoring import wait_turn

    with TestClient(create_app(settings_for(tmp_path, workers=True))) as client:
        create_group(client)
        application = client.app.state.application
        observed = []
        for name, description, voice in (
            (
                "阿岑",
                "内向，慢热，不愿透露私事，喜欢安静，做事谨慎。",
                "说话简短直接，不愿谈私事时明确拒绝，不主动长篇解释。",
            ),
            (
                "晴川",
                "开朗热情，喜欢主动和人聊天，愿意分享想法，乐于讲具体细节。",
                "自然热情，喜欢用具体生活例子说明，认真回答时愿意展开感受和原因。",
            ),
        ):
            draft, _ = create_draft(
                client,
                name,
                description=description,
                profile=description + "小时候在海边生活，祖母陪自己散步。",
                voice=voice,
                story="小时候在海边生活，祖母陪自己散步。",
                interview=selected(client),
            )
            draft = action(client, draft, "stages/basic/confirm")
            draft = action(client, draft, "stages/story/confirm")
            with application.database.read() as connection:
                tables = (
                    "messages",
                    "thoughts",
                    "character_instances",
                    "character_state_entries",
                    "relationship_state",
                    "relation_evidence",
                    "memory_entries",
                )
                # 只比较正式业务表，独立创作记录可以正常增加。
                before = {
                    table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
                    for table in tables
                }
            response = post(
                client,
                draft,
                "candidates",
                candidate_id=str(uuid4()),
                operation="interview",
                question_ids=["conversation_habit", "emotional_recovery"],
            )
            assert response.status_code == 201, response.text
            candidate = response.json()
            assert (
                candidate["model_profile"]
                == application.models.task_routing.route_for(
                    "character_interview"
                    if "character_interview" in application.models.task_routing.task_profiles
                    else "conversation_reply"
                ).resolved_profile
            )
            assert candidate["frozen_input"]["interview_basis"]["voice"] == voice
            observed.append(candidate["output"])
            with application.database.read() as connection:
                for table in tables:
                    assert [
                        tuple(row) for row in connection.execute(f"SELECT * FROM {table}")
                    ] == before[table]
            print("PERSONA_INTERVIEW", name, candidate["output"])
            # 删除整份采访后，人物按故事阶段结束；采访结果只供作者审核。
            draft = save(client, draft, interview=[])
            blueprint, _ = confirm(client, draft)
            if name == "晴川":
                response = client.post(
                    "/api/communities/community/characters",
                    json={
                        "player_id": "alice",
                        "character_id": "situation-character",
                        "blueprint_id": blueprint["blueprint_id"],
                    },
                )
                assert response.status_code == 201, response.text
                deadline = time.monotonic() + 30
                while time.monotonic() < deadline:
                    with application.database.read() as connection:
                        instance = application.characters.instances.get(
                            connection, "community", "situation-character"
                        )
                    if instance.memory_status == "ready":
                        break
                    time.sleep(0.1)
                else:
                    pytest.fail("Character memory preparation did not finish")
                response = client.post(
                    "/api/communities/community/conversations",
                    json={
                        "player_id": "alice",
                        "conversation_id": "situations",
                        "kind": "direct",
                        "actors": [
                            {"kind": "player", "actor_id": "alice"},
                            {"kind": "character", "actor_id": "situation-character"},
                        ],
                    },
                )
                assert response.status_code == 201, response.text
                previous_turn = None
                for index, text in enumerate(
                    (
                        "今天有空，随便聊聊，你在忙什么？",
                        "认真问你一个问题：祖母陪你海边散步，对你的价值观有什么影响？愿意说说具体的感受和原因吗？",
                    )
                ):
                    response = client.post(
                        "/api/conversations/situations/messages",
                        json={
                            "player_id": "alice",
                            "client_message_id": f"situation-{index}",
                            "text": text,
                        },
                    )
                    assert response.status_code == 202, response.text
                    turn = wait_turn(client, "situations", after=previous_turn)
                    previous_turn = turn["social_turn_id"]
                with application.database.read() as connection:
                    print(
                        "SITUATION_MESSAGES",
                        [
                            dict(row)
                            for row in connection.execute(
                                "SELECT text FROM messages WHERE conversation_id='situations'"
                            )
                        ],
                    )
        assert observed[0] != observed[1]
        conflict, _ = create_draft(
            client,
            "矛盾材料人物",
            description="从不喝咖啡，明确讨厌咖啡。",
            profile="我每天都喝咖啡，我喜欢咖啡。",
        )
        conflict = action(client, conflict, "stages/basic/confirm")
        response = post(
            client, conflict, "candidates", candidate_id=str(uuid4()), operation="calibrate"
        )
        assert response.status_code == 201, response.text
        candidate = response.json()
        assert candidate["output"]["conflicts"], candidate
        print("EXPLICIT_CONFLICT", candidate["output"]["conflicts"])
        response = post(client, conflict, f"candidates/{candidate['candidate_id']}/accept")
        assert (
            response.status_code == 409
            and response.json()["error"]["code"] == "calibration_conflict"
        )
        assert (
            client.get(
                f"/api/character-drafts/{conflict['draft_id']}", params={"player_id": "alice"}
            ).json()["content"]
            == conflict["content"]
        )
        conflict = save(client, conflict, profile="我从不喝咖啡，讨厌咖啡。")
        conflict = action(client, conflict, "stages/basic/confirm")
        conflict = action(client, conflict, "documents/confirm", acknowledge_documents_match=True)
        confirm(client, conflict)
