from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from support.application import settings_for
from support.authoring import action, create_draft
from support.http import create_group

from echo_commons.app.main import create_app
from echo_commons.modules.characters.services.relationship_initialization import validate_seeds
from echo_commons.modules.characters.services.wiki_authoring import extract_article


def register(client, name, *, player="alice"):
    response = client.post(
        "/api/character-people",
        json=dict(
            player_id=player,
            person_id=str(uuid4()),
            display_name=name,
            description="作者确认的人物",
        ),
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_relationship_materials_use_confirmed_people_and_existing_workflow(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        observer = register(client, "林夏")
        target = register(client, "周晴")
        draft, _ = create_draft(client)
        draft = action(client, draft, "stages/basic/confirm")
        content = draft["content"] | dict(
            person_id=observer["person_id"],
            relationships=[
                dict(
                    relationship_id=str(uuid4()),
                    target_person_id=target["person_id"],
                    target_name="周晴",
                    content="周晴是我认识多年的朋友，曾陪我修好旧钟。",
                )
            ],
        )
        url = f"/api/character-drafts/{draft['draft_id']}"
        response = client.put(
            url, json=dict(player_id="alice", expected_revision=draft["revision"], content=content)
        )
        assert response.status_code == 200, response.text
        saved = response.json()
        assert saved["workflow"]["story"] == "pending"
        saved = action(client, saved, "stages/story/confirm")
        saved = action(client, saved, "documents/confirm", acknowledge_documents_match=True)
        result = client.post(
            url + "/confirm",
            json=dict(
                player_id="alice",
                expected_revision=saved["revision"],
                acknowledge_fixed_background=True,
            ),
        )
        assert result.status_code == 201, result.text
        blueprint = result.json()
        assert blueprint["content"]["relationships"] == content["relationships"]
        created = client.post(
            "/api/communities/community/characters",
            json=dict(
                player_id="alice",
                blueprint_id=blueprint["blueprint_id"],
                character_id="relationship-character",
            ),
        )
        assert created.status_code == 201, created.text
        assert created.json()["memory_phase"] == "relationships"
        application = client.app.state.application
        with application.database.read() as connection:
            materials = application.characters.catalog.author_materials(
                connection, blueprint["blueprint_id"], blueprint["content_version"]
            )
            assert materials[0].kind == "relationship"
            assert "周晴" in materials[0].content
            assert connection.execute("SELECT count(*) FROM relationship_state").fetchone()[0] == 0
        copied = client.post(url + "/copy", json=dict(player_id="alice", draft_id=str(uuid4())))
        assert copied.status_code == 201, copied.text
        assert copied.json()["content"]["relationships"] == content["relationships"]
        changed = saved["content"] | dict(relationships=[])
        # 固定模板的原草稿不再接受编辑。
        assert (
            client.put(
                url,
                json=dict(player_id="alice", expected_revision=saved["revision"], content=changed),
            ).status_code
            == 409
        )


def test_person_registration_binding_and_unknown_references(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        person = register(client, "作者身份")
        assert client.post("/api/character-people", json=person).status_code == 201
        assert (
            client.post(
                "/api/character-people", json=person | dict(display_name="另一个人")
            ).status_code
            == 409
        )
        binding = dict(
            player_id="alice", person_id=person["person_id"], actor_kind="player", actor_id="alice"
        )
        url = "/api/communities/community/person-bindings"
        assert client.put(url, json=binding).status_code == 200
        assert client.put(url, json=binding).status_code == 200
        other = register(client, "另一身份")
        assert client.put(url, json=binding | dict(person_id=other["person_id"])).status_code == 409
        draft, _ = create_draft(client)
        content = draft["content"] | dict(
            relationships=[
                dict(
                    relationship_id=str(uuid4()),
                    target_person_id=str(uuid4()),
                    target_name="未登记人物",
                    content="旧友",
                )
            ]
        )
        response = client.put(
            f"/api/character-drafts/{draft['draft_id']}",
            json=dict(player_id="alice", expected_revision=draft["revision"], content=content),
        )
        assert response.status_code == 404
        visible = client.get("/api/character-people", params=dict(player_id="bob")).json()
        assert [item["person_id"] for item in visible] == [person["person_id"]]


def test_relationship_analysis_keeps_confirmed_identity_and_evidence():
    identity = str(uuid4())
    material = dict(relationships=[dict(relationship_id=identity, content="我们一起修好了旧钟。")])
    output = dict(
        relationships=[
            dict(
                relationship_id=identity,
                acquaintance=True,
                affection=60,
                trust=65,
                attachment=10,
                attitude="愿意一起工作",
                evidence_quote="一起修好了旧钟",
                support_quote="一起修好了旧钟",
            )
        ]
    )
    assert str(validate_seeds(output, material).relationships[0].relationship_id) == identity
    with pytest.raises(ValueError, match="confirmed material IDs"):
        validate_seeds(dict(relationships=[]), material)
    invalid = output["relationships"][0] | dict(evidence_quote="另一个人告诉了我秘密")
    with pytest.raises(ValueError, match="quote the confirmed"):
        validate_seeds(dict(relationships=[invalid]), material)


def test_wiki_article_uses_template_body_without_navigation_or_scripts():
    paragraph = "作者提供的角色经历与关系材料。" * 30
    html = (
        '<html><body><nav>全站菜单</nav><template id="MOE_SKIN_TEMPLATE_BODYCONTENT">'
        f'<div class="mw-parser-output"><p>{paragraph}</p>'
        '<script>不要执行网页脚本</script><div class="navbox">其它作品导航</div>'
        "</div></template></body></html>"
    )
    assert extract_article(html) == paragraph


def test_community_cleanup_removes_bindings_and_preserves_person_library(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client, memory_mode="simple")
        person = register(client, "社群中的作者")
        bound = client.put(
            "/api/communities/community/person-bindings",
            json=dict(
                player_id="alice",
                person_id=person["person_id"],
                actor_kind="player",
                actor_id="alice",
            ),
        )
        assert bound.status_code == 200, bound.text
        assert (
            client.patch(
                "/api/communities/community/status",
                json=dict(
                    player_id="alice",
                    status="paused",
                    expected_version=1,
                ),
            ).status_code
            == 200
        )
        response = client.post(
            "/internal/maintenance/cleanup",
            json=dict(
                community_ids=["community"],
                dry_run=False,
            ),
        )
        assert response.status_code == 200, response.text
        result = response.json()
        assert result["deleted"] and result["counts"]["character_person_bindings"] == 1
        people = client.get("/api/character-people", params=dict(player_id="alice")).json()
        assert [item["person_id"] for item in people] == [person["person_id"]]


def test_player_cleanup_respects_another_authors_confirmed_person_references(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client, memory_mode="simple")
        person = register(client, "已登记人物")
        assert (
            client.put(
                "/api/communities/community/person-bindings",
                json=dict(
                    player_id="alice",
                    person_id=person["person_id"],
                    actor_kind="player",
                    actor_id="alice",
                ),
            ).status_code
            == 200
        )
        draft = client.post(
            "/api/character-drafts",
            json=dict(
                player_id="bob",
                draft_id=str(uuid4()),
                display_name="另一个作者的人物",
                relationships=[
                    dict(
                        relationship_id=str(uuid4()),
                        target_person_id=person["person_id"],
                        target_name=person["display_name"],
                        content="曾经一起工作。",
                    )
                ],
            ),
        )
        assert draft.status_code == 201, draft.text
        assert (
            client.patch(
                "/api/communities/community/status",
                json=dict(
                    player_id="alice",
                    status="paused",
                    expected_version=1,
                ),
            ).status_code
            == 200
        )
        response = client.post(
            "/internal/maintenance/cleanup",
            json=dict(
                community_ids=["community"],
                player_ids=["alice"],
                dry_run=False,
            ),
        )
        assert response.status_code == 409, response.text
        assert any(
            item["kind"] == "character_person_reference" for item in response.json()["blockers"]
        )
        assert (
            client.get("/api/character-people", params=dict(player_id="alice")).status_code == 200
        )
