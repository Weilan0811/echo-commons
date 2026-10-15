import json
from uuid import uuid4

from fastapi.testclient import TestClient
from support.application import settings_for
from support.authoring import action, create_draft
from support.http import create_group

from echo_commons.agents.authoring import interview_review_messages
from echo_commons.app.main import create_app
from echo_commons.modules.characters.domain.authoring import InterviewRequest


def test_interview_freezes_actual_prompt_and_preserves_previous_candidate(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        draft, _ = create_draft(client, story="小时候在海边住过，每周末跟外婆散步。")
        draft = action(client, draft, "stages/basic/confirm")
        draft = action(client, draft, "stages/story/confirm")
        template = client.get("/api/character-authoring/template").json()
        questions = [
            dict(question_id=item["id"], question=item["question"], answer="")
            for item in template["interview"][:10]
        ]
        response = client.put(
            f"/api/character-drafts/{draft['draft_id']}",
            json={
                "player_id": "alice",
                "expected_revision": draft["revision"],
                "content": draft["content"] | {"interview": questions},
            },
        )
        assert response.status_code == 200, response.text
        draft = action(
            client, response.json(), "documents/confirm", acknowledge_documents_match=True
        )
        service = client.app.state.application.authoring
        request = InterviewRequest(
            candidate_id=uuid4(),
            expected_revision=draft["revision"],
            operation="interview",
            question_ids=(questions[0]["question_id"],),
        )
        first, _, _, created = service.start_candidate("alice", draft["draft_id"], request)
        assert created
        frozen = json.loads(first["request_json"])
        assert frozen["prompt_version"] == "2.0"
        assert service.agent.prompts["interview"] in frozen["prompt"]
        assert frozen["interview_review_prompt"] == service.agent.interview_review
        assert (
            frozen["review_model_profile"]
            == service.routing.route_for("character_interview_review").resolved_profile
        )
        assert "你主动提起未被记录的个人经历" not in frozen["prompt"]
        assert "expression_guidance" not in frozen["prompt"]
        assert frozen["interview_basis"]["expression_guidance"] == ""
        assert frozen["interview_basis"]["agent_contract"] == service.agent.prompts["interview"]
        assert frozen["interview_basis"]["story"] == draft["content"]["story"]
        review = interview_review_messages(frozen, None, "invalid_model_output")
        assert review[0].content == frozen["interview_review_prompt"]
        reviewed = json.loads(review[1].content)
        assert [item["id"] for item in reviewed["selected_questions"]] == list(request.question_ids)
        assert reviewed["character_materials"] == frozen["content"]
        assert reviewed["request"] == frozen["request"]
        assert frozen["review_reasoning_effort"] == "low"
        previous = first["request_json"]
        other = request.model_copy(
            update={"candidate_id": uuid4(), "question_ids": (questions[1]["question_id"],)}
        )
        second, _, _, created = service.start_candidate("alice", draft["draft_id"], other)
        assert created
        assert json.loads(second["request_json"])["interview_basis"] == frozen["interview_basis"]
        repeated, _, _, created = service.start_candidate("alice", draft["draft_id"], request)
        assert not created and repeated["request_json"] == previous
