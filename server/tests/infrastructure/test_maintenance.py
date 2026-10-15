import asyncio
from contextlib import AsyncExitStack
from pathlib import Path
from uuid import uuid4

import httpx
import pytest
from fastapi.testclient import TestClient
from httpx_sse import connect_sse
from test_character_authoring import confirm, create_draft
from test_http_api import create_group
from test_management_api import seal
from test_realtime import cursor, next_event, running_server

from echo_commons.agents.contracts.invocation import InvocationPurpose
from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.app.main import create_app
from echo_commons.app.settings import Settings
from echo_commons.execution.clock import utc_now
from echo_commons.execution.recovery import decision
from echo_commons.infrastructure.observability.outbox import claim_traces, deliver_trace
from echo_commons.modules.characters.domain.authoring import BasicRequest
from echo_commons.modules.maintenance.repository import TABLES
from echo_commons.modules.memory.domain.policy import MemoryPolicy, VectorPolicy

URL = "/internal/maintenance/cleanup"


def isolated_settings(tmp_path):
    return Settings(
        database_path=str(tmp_path / "test.sqlite3"),
        asset_directory=str(tmp_path / "assets/images"),
        model_registry_path=str(Path("config/model-registry.toml").resolve()),
        model_secrets_path=str(tmp_path / "absent-credentials.toml"),
        worker_enabled=False,
        quiet_window_seconds=0,
        log_path=str(tmp_path / "logs/test.log"),
    )


@pytest.fixture
def client(tmp_path):
    with TestClient(create_app(isolated_settings(tmp_path))) as client:
        create_group(client, memory_mode="simple")
        yield client


def pause(client):
    response = client.patch(
        "/api/communities/community/status",
        json={
            "player_id": "alice",
            "status": "paused",
            "expected_version": 1,
        },
    )
    assert response.status_code == 200, response.text


def send_and_plan(client):
    response = client.post(
        "/api/conversations/conversation/messages",
        json={
            "player_id": "alice",
            "client_message_id": "cleanup-message",
            "text": "小槿，你好",
        },
    )
    assert response.status_code == 202, response.text
    application = client.app.state.application
    assert application.planner.plan()
    return application


def test_cleanup_preview_execution_scope_and_repeated_request(client):
    application = send_and_plan(client)
    draft, _ = create_draft(client)
    assert (
        client.post(
            "/api/communities",
            json={
                "player_id": "bob",
                "community_id": "keep",
                "name": "保留",
                "timezone": "UTC",
            },
        ).status_code
        == 201
    )
    assert (
        client.patch(
            "/api/communities/keep/status",
            json={
                "player_id": "bob",
                "status": "active",
                "expected_version": 0,
            },
        ).status_code
        == 200
    )
    assert (
        client.post(
            "/api/communities/keep/characters",
            json={
                "player_id": "bob",
                "character_id": "keep-character",
                "blueprint_id": "xiaojin",
                "memory_mode": "simple",
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/communities/keep/conversations",
            json={
                "player_id": "bob",
                "conversation_id": "keep-conversation",
                "kind": "direct",
                "actors": [
                    {"kind": "player", "actor_id": "bob"},
                    {"kind": "character", "actor_id": "keep-character"},
                ],
            },
        ).status_code
        == 201
    )
    assert (
        client.post(
            "/api/conversations/keep-conversation/messages",
            json={
                "player_id": "bob",
                "client_message_id": "keep-message",
                "text": "需要保留的消息",
            },
        ).status_code
        == 202
    )
    pause(client)
    with application.database.read() as connection:
        high = connection.execute("SELECT MAX(sequence) FROM realtime_events").fetchone()[0]
        keep_event = tuple(
            connection.execute("SELECT * FROM realtime_events WHERE community_id='keep'").fetchone()
        )
        keep_documents = [
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM memory_search_documents WHERE community_id='keep' "
                "ORDER BY document_id"
            )
        ]
        keep_fts = [
            tuple(row)
            for row in connection.execute(
                "SELECT rowid,* FROM memory_search_fts WHERE rowid IN "
                "(SELECT document_id FROM memory_search_documents WHERE community_id='keep') "
                "ORDER BY rowid"
            )
        ]
    preview = client.post(URL, json={"community_ids": ["community", "missing", "community"]})
    assert preview.status_code == 200, preview.text
    body = preview.json()
    assert body["dry_run"] and not body["deleted"] and not body["blockers"]
    assert body["counts"]["communities"] == 1
    assert body["counts"]["messages"] == 1
    assert body["counts"]["conversation_tasks"] > 0
    assert body["counts"]["memory_search_fts"] > 0
    assert body["counts"]["trace_outbox"] > 0
    assert body["missing"]["community_ids"] == ["missing"]
    with application.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM communities").fetchone()[0] == 2
    response = client.post(URL, json={"community_ids": ["community"], "dry_run": False})
    assert response.status_code == 200, response.text
    assert response.json()["deleted"] and response.json()["counts"] == body["counts"]
    with application.database.read() as connection:
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        assert connection.execute("PRAGMA foreign_keys").fetchone()[0] == 1
        assert (
            tuple(
                connection.execute(
                    "SELECT * FROM realtime_events WHERE community_id='keep'"
                ).fetchone()
            )
            == keep_event
        )
        assert [
            tuple(row)
            for row in connection.execute(
                "SELECT * FROM memory_search_documents ORDER BY document_id"
            )
        ] == keep_documents
        assert [
            tuple(row)
            for row in connection.execute("SELECT rowid,* FROM memory_search_fts ORDER BY rowid")
        ] == keep_fts
        assert connection.execute("SELECT COUNT(*) FROM trace_outbox").fetchone()[0] == 1
        assert connection.execute("SELECT text FROM messages").fetchone()[0] == "需要保留的消息"
        assert connection.execute("SELECT COUNT(*) FROM players").fetchone()[0] == 2
        assert (
            connection.execute(
                "SELECT COUNT(*) FROM character_authoring_drafts WHERE draft_id=?",
                (draft["draft_id"],),
            ).fetchone()[0]
            == 1
        )
    repeated = client.post(URL, json={"community_ids": ["community"], "dry_run": False}).json()
    assert repeated["missing"]["community_ids"] == ["community"]
    assert not any(repeated["counts"].values())
    assert (
        client.post(
            "/api/communities",
            json={
                "player_id": "alice",
                "community_id": "new",
                "name": "新社群",
                "timezone": "UTC",
            },
        ).status_code
        == 201
    )
    assert (
        client.patch(
            "/api/communities/new/status",
            json={
                "player_id": "alice",
                "status": "active",
                "expected_version": 0,
            },
        ).status_code
        == 200
    )
    with application.database.read() as connection:
        assert connection.execute("SELECT MAX(sequence) FROM realtime_events").fetchone()[0] > high


def test_cleanup_requires_explicit_scope_and_pause(client):
    for body in (
        {},
        {"player_ids": [""]},
        {"community_ids": ["community"], "all": True},
        {"community_ids": ["community"], "dry_run": "false"},
    ):
        assert client.post(URL, json=body).status_code == 422
    preview = client.post(URL, json={"community_ids": ["community"]}).json()
    assert preview["blockers"][0]["kind"] == "community"
    blocked = client.post(URL, json={"community_ids": ["community"], "dry_run": False})
    assert blocked.status_code == 409 and not blocked.json()["deleted"]


def test_cleanup_players_and_fixed_blueprint_references(client):
    draft, _ = create_draft(client)
    blueprint, _ = confirm(client, draft)
    assert (
        client.post(
            "/api/communities",
            json={
                "player_id": "alice",
                "community_id": "keep",
                "name": "保留",
                "timezone": "UTC",
            },
        ).status_code
        == 201
    )
    response = client.post(
        "/api/communities/keep/characters",
        json={
            "player_id": "alice",
            "character_id": "custom",
            "blueprint_id": blueprint["blueprint_id"],
            "memory_mode": "simple",
        },
    )
    assert response.status_code == 201, response.text
    pause(client)
    body = {
        "community_ids": ["community"],
        "draft_ids": [draft["draft_id"]],
        "player_ids": ["alice"],
        "dry_run": False,
    }
    blocked = client.post(URL, json=body)
    assert blocked.status_code == 409, blocked.text
    kinds = {blocker["kind"] for blocker in blocked.json()["blockers"]}
    assert kinds == {"character", "player"}
    body["community_ids"].append("keep")
    response = client.post(URL, json=body)
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["custom_character_blueprints"] == 1
    with client.app.state.application.database.read() as connection:
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        assert [row[0] for row in connection.execute("SELECT player_id FROM players")] == ["bob"]


def test_cleanup_player_keeps_unselected_draft(client):
    draft, _ = create_draft(client)
    pause(client)
    response = client.post(
        URL, json={"community_ids": ["community"], "player_ids": ["alice"], "dry_run": False}
    )
    assert response.status_code == 409
    assert any("草稿" in item["reason"] for item in response.json()["blockers"])
    response = client.post(
        URL,
        json={
            "community_ids": ["community"],
            "draft_ids": [draft["draft_id"]],
            "player_ids": ["alice", "bob"],
            "dry_run": False,
        },
    )
    assert response.status_code == 200, response.text


def test_cleanup_checks_processing_authoring_request(client):
    draft, _ = create_draft(client)
    # 使用正式创作入口建立正在执行的候选，随后检查维护范围。
    application = client.app.state.application
    candidate, _, _, _ = application.authoring.start_candidate(
        "alice",
        draft["draft_id"],
        BasicRequest(candidate_id=uuid4(), operation="basic", expected_revision=draft["revision"]),
    )
    response = client.post(URL, json={"draft_ids": [draft["draft_id"]], "dry_run": False})
    assert response.status_code == 409, response.text
    assert response.json()["blockers"][0]["object_id"] == candidate["candidate_id"]


def test_cleanup_processing_task_preview(client):
    application = send_and_plan(client)
    lease = asyncio.run(application.queue.claim("maintenance-test", utc_now()))
    assert lease is not None
    response = client.post(URL, json={"community_ids": ["community"]})
    assert response.status_code == 200
    assert any(
        item["kind"] == "conversation_task" and item["object_id"] == lease.task_id
        for item in response.json()["blockers"]
    )


def test_cleanup_reflection_task_and_associated_memory(client):
    application = send_and_plan(client)
    segment = seal(client)["segment"]
    scheduled = client.post(
        "/internal/communities/community/characters/first/reflection/segments",
        json={"segment_id": segment["segment_id"]},
    )
    assert scheduled.status_code == 202, scheduled.text
    lease = client.portal.call(application.reflection_queue.claim, "cleanup-reflection", utc_now())
    assert lease is not None
    pause(client)
    response = client.post(URL, json={"community_ids": ["community"], "dry_run": False})
    assert response.status_code == 409, response.text
    assert any(
        item["kind"] == "reflection_node" and item["object_id"] == lease.task_id
        for item in response.json()["blockers"]
    )
    client.portal.call(
        application.reflection_queue.apply_recovery,
        lease,
        utc_now(),
        decision("execution_interrupted", FailureCategory.HARNESS, RecoveryAction.FAIL),
    )
    response = client.post(URL, json={"community_ids": ["community"], "dry_run": False})
    assert response.status_code == 200, response.text
    assert response.json()["counts"]["memory_segments"] == 1
    assert response.json()["counts"]["reflection_graph_runs"] == 1
    with application.database.read() as connection:
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_cleanup_waits_for_real_dispatcher_after_pause(client):
    application = send_and_plan(client)
    worker = application.supervisor.workers["conversations-0"]
    backend = application.handler.execution.agents.bindings[
        InvocationPurpose.CONVERSATION_REPLY
    ].backend
    budget = backend._loop.gateway
    slots = AsyncExitStack()

    async def occupy_and_dispatch():
        for _ in range(application.settings.model_concurrency):
            await slots.enter_async_context(budget.slot())
        task = asyncio.create_task(worker.dispatcher.dispatch_once())
        async with asyncio.timeout(5):
            while not budget._waiting:
                assert not task.done()
                await asyncio.sleep(0.01)
        return task

    task = client.portal.call(occupy_and_dispatch)
    try:
        pause(client)
        blocked = client.post(URL, json={"community_ids": ["community"], "dry_run": False})
        assert blocked.status_code == 409, blocked.text
        assert any(item["kind"] == "runtime_task" for item in blocked.json()["blockers"])
    finally:

        async def release():
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)
            await slots.aclose()

        client.portal.call(release)
    assert worker.dispatcher.active_task_id is None
    cleaned = client.post(URL, json={"community_ids": ["community"], "dry_run": False})
    assert cleaned.status_code == 200, cleaned.text


def test_cleanup_covers_current_business_tables(client):
    with client.app.state.application.database.read() as connection:
        actual = {
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%'"
            )
            if not row[0].startswith("memory_search_fts_")
        }
    assert actual - {"schema_migrations", "realtime_event_state"} == set(TABLES)


def test_cleanup_trace_delivery_and_saved_traces(client):
    application = send_and_plan(client)
    pause(client)
    with application.database.transaction() as connection:
        claimed = claim_traces(connection, "cleanup-traces", utc_now(), 90, 3, 100)
    assert claimed
    blocked = client.post(URL, json={"community_ids": ["community"], "dry_run": False})
    assert blocked.status_code == 409
    assert {item["object_id"] for item in blocked.json()["blockers"]} == set(claimed)
    with application.database.transaction() as connection:
        for trace_id in claimed:
            assert deliver_trace(connection, trace_id, "cleanup-traces", utc_now()) == 1
    cleaned = client.post(URL, json={"community_ids": ["community"], "dry_run": False})
    assert cleaned.status_code == 200, cleaned.text
    assert cleaned.json()["counts"]["traces"] == len(claimed)
    with application.database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM traces").fetchone()[0] == 0


def test_cleanup_vector_selection_and_real_missing_configuration(tmp_path):
    settings = isolated_settings(tmp_path).model_copy(
        update={"memory": MemoryPolicy(vector=VectorPolicy(enabled=True))}
    )
    with TestClient(create_app(settings)) as client:
        create_group(client, memory_mode="simple")
        application = client.app.state.application
        worker = application.supervisor.workers["memory-vectors"]
        rows = worker._pending(worker.gateway.identity)
        assert rows and worker.active_document_ids
        pause(client)
        blocked = client.post(URL, json={"community_ids": ["community"], "dry_run": False})
        assert blocked.status_code == 409, blocked.text
        assert {item["kind"] for item in blocked.json()["blockers"]} == {"memory_vector"}
        assert client.portal.call(worker.run_once) is False
        assert not worker.active_document_ids
        cleaned = client.post(URL, json={"community_ids": ["community"], "dry_run": False})
        assert cleaned.status_code == 200, cleaned.text
        assert cleaned.json()["counts"]["memory_vector_failures"] > 0


def test_cleanup_transaction_rolls_back_real_sqlite_failure(client):
    pause(client)
    database = client.app.state.application.database
    with database.transaction() as connection:
        connection.execute(
            "CREATE TRIGGER prevent_test_player_delete BEFORE DELETE ON players "
            "BEGIN SELECT RAISE(ABORT,'player deletion rejected'); END"
        )
    response = client.post(
        URL, json={"community_ids": ["community"], "player_ids": ["alice"], "dry_run": False}
    )
    assert response.status_code == 500, response.text
    with database.read() as connection:
        assert connection.execute("SELECT COUNT(*) FROM communities").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM character_instances").fetchone()[0] == 2
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_cleanup_closes_deleted_community_sse(tmp_path):
    with running_server(isolated_settings(tmp_path)) as (client, application):
        create_group(client, memory_mode="simple")
        pause(client)
        value = cursor(client)
        with (
            httpx.Client(
                base_url=str(client.base_url), timeout=5, trust_env=False
            ) as stream_client,
            connect_sse(
                stream_client,
                "GET",
                "/api/communities/community/events",
                params={"player_id": "alice", "cursor": value},
            ) as stream,
        ):
            events = stream.iter_sse()
            message = client.post(
                "/api/conversations/conversation/messages",
                json={
                    "player_id": "alice",
                    "client_message_id": "sse-before-cleanup",
                    "text": "清理前确认订阅",
                },
            )
            assert message.status_code == 202
            next_event(events, "conversation.message_created")
            response = client.post(URL, json={"community_ids": ["community"], "dry_run": False})
            assert response.status_code == 200, response.text
            next_event(events, "access_revoked")
            assert list(events) == []
        with application.database.read() as connection:
            assert connection.execute("SELECT COUNT(*) FROM realtime_events").fetchone()[0] == 0
