from importlib.resources import files

from fastapi.testclient import TestClient
from historical_database import copy_to_historical_schema
from test_application_lifecycle import settings_for
from test_character_authoring import confirm, create_draft
from test_http_api import create_group

from echo_commons.app.main import create_app
from echo_commons.infrastructure.database.migrations import initialize


def test_mode_readiness_idempotency_and_retry_scope(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        draft, _ = create_draft(client, story="小时候在青石镇长大，祖母教我修理旧钟。")
        blueprint, _ = confirm(client, draft)
        body = dict(
            player_id="alice", blueprint_id=blueprint["blueprint_id"], character_id="authored"
        )
        url = "/api/communities/community/characters"
        response = client.post(url, json=body)
        assert response.status_code == 201, response.text
        assert response.json()["memory_mode"] == "simple"
        assert response.json()["memory_status"] == "preparing"
        assert client.post(url, json=body).json() == response.json()
        assert client.post(url, json=body | {"memory_mode": "full"}).status_code == 409
        conversation = dict(
            player_id="alice",
            kind="direct",
            conversation_id="blocked",
            actors=[
                dict(kind="player", actor_id="alice"),
                dict(kind="character", actor_id="authored"),
            ],
        )
        denied = client.post("/api/communities/community/conversations", json=conversation)
        assert denied.status_code == 409
        assert denied.json()["error"]["code"] == "character_memory_not_ready"
        application = client.app.state.application
        with application.database.transaction() as connection:
            assert (
                connection.execute("SELECT COUNT(*) FROM memory_author_materials").fetchone()[0]
                == 1
            )
            assert (
                connection.execute("SELECT COUNT(*) FROM memory_initializations").fetchone()[0] == 1
            )
            connection.execute(
                "UPDATE character_instances SET memory_status='failed' "
                "WHERE character_id='authored'"
            )
            connection.execute(
                "UPDATE memory_initializations SET error_code='initialization_failed'"
            )
        retry = url + "/authored/memory/retry"
        assert client.post(retry, json=dict(player_id="bob")).status_code == 404
        response = client.post(retry, json=dict(player_id="alice"))
        assert response.status_code == 200, response.text
        assert response.json()["memory_status"] == "preparing"
        assert response.json()["memory_error_code"] is None
        assert client.post(retry, json=dict(player_id="alice")).json() == response.json()
        bare, _ = create_draft(client)
        bare_blueprint, _ = confirm(client, bare)
        for mode in ("simple", "full"):
            response = client.post(
                url,
                json=dict(
                    player_id="alice", blueprint_id=bare_blueprint["blueprint_id"], memory_mode=mode
                ),
            )
            assert response.status_code == 201, response.text
            assert response.json()["memory_mode"] == mode
            assert response.json()["memory_status"] == "ready"


def test_version_five_upgrade_preserves_facts_and_restores_author_sources(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        draft, _ = create_draft(client, story="小时候在青石镇长大。")
        blueprint, _ = confirm(client, draft)
        response = client.post(
            "/api/communities/community/characters",
            json=dict(
                player_id="alice", blueprint_id=blueprint["blueprint_id"], character_id="old-custom"
            ),
        )
        assert response.status_code == 201, response.text
        sql = tmp_path / "version5"
        sql.mkdir()
        for source in files("echo_commons.infrastructure.database.sql").iterdir():
            if source.name.endswith(".sql") and int(source.name[:4]) <= 5:
                (sql / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
        database = copy_to_historical_schema(
            client.app.state.application.database, sql, tmp_path / "upgrade5.sqlite3"
        )
        tables = (
            "messages",
            "thoughts",
            "memory_entries",
            "relationship_state",
            "character_state_entries",
            "custom_character_blueprints",
            "memory_search_documents",
        )
        with database.read() as connection:
            before = {
                table: [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
                for table in tables
            }
        assert initialize(database) == initialize(database) == 6
        with database.read() as connection:
            for table in tables:
                current = [tuple(row) for row in connection.execute(f"SELECT * FROM {table}")]
                assert current == before[table]
            assert all(
                tuple(row) == ("full", "ready")
                for row in connection.execute(
                    "SELECT memory_mode,memory_status FROM character_instances"
                )
            )
            row = connection.execute("SELECT * FROM memory_author_materials").fetchone()
            assert row["character_id"] == "old-custom"
            assert row["content"] == draft["content"]["story"]
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
