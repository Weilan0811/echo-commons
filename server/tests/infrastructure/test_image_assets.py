from importlib.resources import files
from io import BytesIO
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from httpx_sse import connect_sse
from PIL import Image
from test_character_authoring import confirm, create_draft
from test_http_api import create_group
from test_realtime import cursor, next_event, running_server

from echo_commons.app.main import create_app
from echo_commons.app.settings import Settings
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.infrastructure.models.registry import load_model_registry
from echo_commons.modules.assets.contracts import GenerationRequest
from echo_commons.shared.realtime import EventKind, EventReference, EventSource, record_event


@pytest.fixture
def client(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "assets.sqlite3"),
        asset_directory=str(tmp_path / "images"),
        model_registry_path=str(Path("config/model-registry.toml").resolve()),
        model_secrets_path=str(tmp_path / "absent-secrets.toml"),
        worker_enabled=False,
    )
    with TestClient(create_app(settings)) as client:
        for player in ("alice", "bob"):
            assert (
                client.post(
                    "/api/players", json={"player_id": player, "display_name": player}
                ).status_code
                == 201
            )
        yield client


def upload(client, purpose="character_illustration", size=(2160, 2700)):
    buffer = BytesIO()
    Image.new("RGB", size, (50, 80, 100)).save(buffer, "PNG")
    response = client.post(
        "/api/assets/images",
        data={"player_id": "alice", "purpose": purpose},
        files={"file": ("input.png", buffer.getvalue(), "image/png")},
    )
    assert response.status_code == 201, response.text
    return response.json()


def test_upload_crop_read_ownership_delete(client):
    illustration = upload(client)
    assert {(i["width"], i["height"]) for i in illustration["images"]} == {(1080, 1350), (540, 675)}
    request = {"player_id": "alice", "client_request_id": "crop-1", "x": 0, "y": 0, "size": 1080}
    url = f"/api/assets/{illustration['asset_id']}/avatar-crops"
    avatar = client.post(url, json=request)
    assert avatar.status_code == 201, avatar.text
    avatar = avatar.json()
    assert client.post(url, json=request).json()["asset_id"] == avatar["asset_id"]
    assert client.post(url, json=request | {"y": 10}).status_code == 409
    assert (
        client.post(url, json=request | {"client_request_id": "bad", "x": 100}).status_code == 400
    )
    for file in avatar["images"]:
        response = client.get(file["url"])
        assert response.headers["content-type"] == "image/webp"
        assert Image.open(BytesIO(response.content)).size == (file["width"], file["height"])
    assert client.get(f"/api/assets/{avatar['asset_id']}?player_id=bob").status_code == 404
    assert (
        client.delete(f"/api/assets/{illustration['asset_id']}?player_id=alice").status_code == 409
    )
    assert client.delete(f"/api/assets/{avatar['asset_id']}?player_id=alice").status_code == 204
    assert (
        client.delete(f"/api/assets/{illustration['asset_id']}?player_id=alice").status_code == 204
    )
    assert not list(client.app.state.application.assets.storage.root.glob("*/*.webp"))


@pytest.mark.parametrize(
    "purpose,size,expected",
    [
        ("community_cover", (3200, 1200), {(1600, 600), (768, 288), (1536, 576)}),
        ("chat_background", (3840, 2160), {(1920, 1080)}),
        ("character_illustration", (100, 125), {(100, 125)}),
    ],
)
def test_purpose_sizes(client, purpose, size, expected):
    asset = upload(client, purpose, size)
    assert {(i["width"], i["height"]) for i in asset["images"]} == expected
    assert (
        client.get("/api/assets?player_id=alice").json()["items"][0]["asset_id"]
        == asset["asset_id"]
    )


def test_invalid_upload_and_missing_credentials(client):
    response = client.post(
        "/api/assets/images",
        data={"player_id": "alice", "purpose": "chat_background"},
        files={"file": ("input.svg", b"<svg/>", "image/svg+xml")},
    )
    assert response.status_code == 400
    response = client.post(
        "/api/image-generations",
        json={
            "player_id": "alice",
            "client_request_id": "generation",
            "purpose": "chat_background",
            "style_id": "soft_illustration",
            "description": "quiet environment",
        },
    )
    assert response.status_code == 503, response.text
    assert response.json()["error"]["code"] == "image_model_unavailable"
    assert len(client.get("/api/assets/generation-styles").json()) == 2


def avatar(client):
    illustration = upload(client)
    response = client.post(
        f"/api/assets/{illustration['asset_id']}/avatar-crops",
        json={
            "player_id": "alice",
            "client_request_id": illustration["asset_id"],
            "x": 0,
            "y": 0,
            "size": 1080,
        },
    )
    assert response.status_code == 201, response.text
    return illustration, response.json()


def test_community_and_character_appearance_versions_events(client):
    create_group(client, memory_mode="simple")
    cover = upload(client, "community_cover", (1600, 600))
    body = {
        "player_id": "alice",
        "expected_version": 1,
        "cover_kind": "asset",
        "cover_ref": cover["asset_id"],
    }
    url = "/api/communities/community/appearance"
    result = client.patch(url, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["state_version"] == 2
    assert client.patch(url, json=body).status_code == 409
    assert (
        client.get("/api/communities?player_id=alice").json()["items"][0]["cover_ref"]
        == cover["asset_id"]
    )
    assert client.delete(f"/api/assets/{cover['asset_id']}?player_id=alice").status_code == 409
    illustration, cropped = avatar(client)
    url = "/api/communities/community/characters/first/appearance"
    request = {"player_id": "alice", "expected_version": 0, "avatar_asset_id": cropped["asset_id"]}
    result = client.patch(url, json=request)
    assert result.status_code == 200, result.text
    assert result.json()["appearance_version"] == 1
    assert result.json()["illustration_url"] == illustration["images"][-1]["url"]
    assert client.patch(url, json=request).status_code == 409
    assert client.delete(f"/api/assets/{cropped['asset_id']}?player_id=alice").status_code == 409
    application = client.app.state.application
    with application.database.read() as connection:
        events = connection.execute(
            "SELECT kind FROM realtime_events WHERE kind LIKE '%appearance_changed'"
        ).fetchall()
        assert {r[0] for r in events} == {
            "community.appearance_changed",
            "character.appearance_changed",
        }
    restored = client.patch(url, json=request | {"expected_version": 1, "avatar_asset_id": None})
    assert restored.status_code == 200
    assert restored.json()["illustration_url"] is None
    assert client.delete(f"/api/assets/{cropped['asset_id']}?player_id=alice").status_code == 204


def test_draft_fixed_avatar_copy_and_cleanup(client):
    create_group(client, memory_mode="simple")
    illustration, cropped = avatar(client)
    draft, _ = create_draft(client, avatar_asset_id=cropped["asset_id"])
    blueprint, _ = confirm(client, draft)
    assert blueprint["avatar_asset_id"] == cropped["asset_id"]
    assert blueprint["avatar_url"].endswith("/images/standard")
    assert blueprint["illustration_url"].startswith(f"/api/assets/{illustration['asset_id']}/")
    response = client.post(
        "/api/communities/community/characters",
        json={
            "player_id": "alice",
            "blueprint_id": blueprint["blueprint_id"],
            "character_id": "custom",
            "memory_mode": "simple",
        },
    )
    assert response.status_code == 201, response.text
    assert response.json()["avatar_url"] == blueprint["avatar_url"]
    cleanup = "/internal/maintenance/cleanup"
    assert client.post(cleanup, json={"asset_ids": [cropped["asset_id"]]}).json()["blockers"]
    assert client.post(cleanup, json={"player_ids": ["alice"]}).json()["blockers"]
    client.patch(
        "/api/communities/community/status",
        json={"player_id": "alice", "expected_version": 1, "status": "paused"},
    )
    body = {
        "community_ids": ["community"],
        "draft_ids": [draft["draft_id"]],
        "asset_ids": [illustration["asset_id"], cropped["asset_id"]],
        "player_ids": ["alice"],
        "dry_run": False,
    }
    result = client.post(cleanup, json=body)
    assert result.status_code == 200, result.text
    assert result.json()["deleted"]
    assert not list(client.app.state.application.assets.storage.root.glob("*/*.webp"))


def test_upload_bounds_formats_and_generated_dimensions(client):
    from echo_commons.infrastructure.assets.images import variants
    from echo_commons.shared.errors import NotFoundError

    image = Image.new("RGB", (1080, 1350))
    files = variants(image, "character_illustration", generated=True)
    assert len(files) == 2
    with pytest.raises(ValueError, match="smaller"):
        variants(Image.new("RGB", (100, 125)), "character_illustration", generated=True)
    with pytest.raises(ValueError, match="aspect"):
        variants(Image.new("RGB", (1350, 1350)), "character_illustration", generated=True)
    application = client.app.state.application
    with pytest.raises(NotFoundError):
        application.assets.upload("absent", "chat_background", b"invalid")
    response = client.post(
        "/api/assets/images",
        data={"player_id": "alice", "purpose": "character_illustration"},
        files={"file": ("too-large.png", b"x" * (5 * 1024 * 1024 + 1), "image/png")},
    )
    assert response.status_code == 400


@pytest.mark.parametrize(
    "purpose,required",
    [
        ("character_illustration", "头顶"),
        ("community_cover", "世界"),
        ("chat_background", "中部必须暗且空"),
    ],
)
def test_frozen_prompt_materials(client, purpose, required):
    request = GenerationRequest(
        player_id="alice",
        client_request_id="prompt",
        purpose=purpose,
        style_id="watercolor",
        description="explicit scene",
        appearance="silver hair",
        scene_context={"time_of_day": "白天", "lighting": "日光", "palette": "青绿色"},
    )
    application = client.app.state.application
    with application.database.read() as connection:
        prompt = application.image_generations.prompt(request, connection)
    for word in (required, "白天", "日光", "青绿色", "水彩", "explicit scene", "silver hair"):
        assert word in prompt
    assert (
        client.post(
            "/api/image-generations", json=request.model_dump() | {"resolution": "4k"}
        ).status_code
        == 422
    )


def test_empty_credentials_and_storage_recovery(client, tmp_path):
    secrets = tmp_path / "empty-test-credentials.toml"
    secrets.write_text('[credentials]\napimart = ""\n', encoding="utf-8")
    registry = load_model_registry(Path("config/model-registry.toml"), secrets)
    assert registry.credentials["apimart"] == ""
    illustration, cropped = avatar(client)
    application = client.app.state.application
    root = application.assets.storage.root
    (root / ".temporary" / "interrupted").mkdir(parents=True)
    (root / "unregistered").mkdir()
    with application.database.transaction() as connection:
        connection.execute("UPDATE image_assets SET status='deleting'")
    application.assets.recover()
    assert not (root / illustration["asset_id"]).exists()
    assert not (root / cropped["asset_id"]).exists()
    assert not (root / "unregistered").exists()
    assert not (root / ".temporary").exists()


def test_appearance_events_over_real_sse(tmp_path):
    settings = Settings(
        database_path=str(tmp_path / "sse.sqlite3"),
        asset_directory=str(tmp_path / "images"),
        model_registry_path=str(Path("config/model-registry.toml").resolve()),
        model_secrets_path=str(tmp_path / "absent-credentials.toml"),
        worker_enabled=False,
    )
    with running_server(settings) as (client, _application):
        create_group(client, memory_mode="simple")
        illustration, cropped = avatar(client)
        url = "/api/communities/community/events"
        with connect_sse(
            client, "GET", url, params={"player_id": "alice", "cursor": cursor(client)}
        ) as source:
            events = source.iter_sse()
            response = client.patch(
                "/api/communities/community/appearance",
                json={
                    "player_id": "alice",
                    "expected_version": 1,
                    "cover_kind": "preset",
                    "cover_ref": "night",
                },
            )
            assert response.status_code == 200, response.text
            assert next_event(events, "community.appearance_changed").json() == {
                "community_id": "community"
            }
            response = client.patch(
                "/api/communities/community/characters/first/appearance",
                json={
                    "player_id": "alice",
                    "expected_version": 0,
                    "avatar_asset_id": cropped["asset_id"],
                },
            )
            assert response.status_code == 200, response.text
            assert next_event(events, "character.appearance_changed").json() == {
                "community_id": "community",
                "character_id": "first",
            }
        characters = client.get("/api/communities/community/characters?player_id=alice").json()
        assert characters[0]["illustration_url"].startswith(
            f"/api/assets/{illustration['asset_id']}/"
        )


def test_version_eleven_upgrade_preserves_event_sequence(tmp_path):
    historical = tmp_path / "version11"
    historical.mkdir()
    for script in files("echo_commons.infrastructure.database.sql").iterdir():
        if script.name.endswith(".sql") and int(script.name[:4]) <= 11:
            (historical / script.name).write_text(
                script.read_text(encoding="utf-8"), encoding="utf-8"
            )
    database = Database(tmp_path / "upgrade.sqlite3")
    assert initialize(database, sql_directory=historical) == 11
    with database.transaction() as connection:
        connection.execute(
            "INSERT INTO communities (community_id,name,timezone,world_time_utc,"
            "created_at_utc,updated_at_utc) VALUES ('world','世界','UTC',?,?,?)",
            ("2026-10-09T00:00:00+00:00",) * 3,
        )
    for _ in range(3):
        with database.transaction() as connection:
            record_event(
                connection,
                EventReference(
                    EventKind.COMMUNITY, "world", "world", EventSource.COMMUNITY, "world"
                ),
            )
    with database.transaction() as connection:
        connection.execute("DELETE FROM realtime_events")
        connection.execute("UPDATE realtime_event_state SET cleaned_through=3")
    assert initialize(database) == 19
    with database.transaction() as connection:
        record_event(
            connection,
            EventReference(
                EventKind.COMMUNITY_APPEARANCE, "world", "world", EventSource.COMMUNITY, "world"
            ),
        )
    with database.read() as connection:
        assert connection.execute("SELECT sequence FROM realtime_events").fetchone()[0] == 4
        assert (
            connection.execute("SELECT cleaned_through FROM realtime_event_state").fetchone()[0]
            == 3
        )
        assert tuple(
            connection.execute("SELECT cover_kind,cover_ref FROM communities").fetchone()
        ) == (None, None)
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
