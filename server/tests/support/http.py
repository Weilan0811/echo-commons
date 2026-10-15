from echo_commons.modules.characters.domain.authoring import AuthoringContent
from echo_commons.modules.characters.templates.loader import load_blueprint_catalog


def create_group(client, *, memory_mode="full"):
    actors = []
    for player in ("alice", "bob"):
        response = client.post("/api/players", json={"player_id": player, "display_name": player})
        assert response.status_code == 201
        actors.append({"kind": "player", "actor_id": player})
    community = client.post(
        "/api/communities",
        json={"player_id": "alice", "community_id": "community", "name": "群聊", "timezone": "UTC"},
    )
    assert community.status_code == 201
    assert (
        client.patch(
            "/api/communities/community/status",
            json={"player_id": "alice", "status": "active", "expected_version": 0},
        ).status_code
        == 200
    )
    assert client.put("/api/communities/community/players/bob").status_code == 200
    blueprints = client.get("/api/blueprints")
    assert blueprints.status_code == 200
    assert blueprints.json()[0]["content_version"] == "0.1.0"
    blueprint_id = "xiaojin"
    if memory_mode == "full":
        from support.authoring import confirm, create_draft

        template = load_blueprint_catalog().blueprint("xiaojin")
        content = AuthoringContent(
            display_name=template.display_name,
            description="基础人物资料。",
            profile=template.profile.content,
            voice=template.voice.content,
            relational_dynamics=template.relational_dynamics.content,
        )
        draft, _ = create_draft(
            client,
            name=template.display_name,
            **content.model_dump(exclude={"display_name"}, mode="json"),
        )
        blueprint, _ = confirm(client, draft)
        blueprint_id = blueprint["blueprint_id"]
    for character in ("first", "second"):
        response = client.post(
            "/api/communities/community/characters",
            json={
                "player_id": "alice",
                "blueprint_id": blueprint_id,
                "character_id": character,
                "memory_mode": memory_mode,
            },
        )
        assert response.status_code == 201
        assert "memory" not in response.json() and "state_entries" not in response.json()
        actors.append({"kind": "character", "actor_id": character})
    response = client.post(
        "/api/communities/community/conversations",
        json={
            "player_id": "alice",
            "kind": "group",
            "actors": actors,
            "conversation_id": "conversation",
        },
    )
    assert response.status_code == 201
    assert "next_sequence" not in response.json()
