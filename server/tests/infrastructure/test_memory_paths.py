import asyncio
from datetime import UTC, datetime
from importlib.resources import files

from fastapi.testclient import TestClient
from historical_database import copy_to_historical_schema
from test_application_lifecycle import settings_for
from test_character_authoring import confirm, create_draft
from test_http_api import create_group

from echo_commons.app.main import create_app
from echo_commons.execution.model_budget import ModelBudget
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.memory.repositories.coverage import CoverageRepository
from echo_commons.modules.memory.repositories.search import SearchRepository
from echo_commons.modules.memory.repositories.segments import SegmentRepository
from echo_commons.modules.memory.services.ingestion import MemoryIngestion
from echo_commons.modules.memory.services.materials import MemoryMaterials, chunk_ranges
from echo_commons.modules.memory.services.retrieval import SearchScope
from echo_commons.modules.memory.services.vectors import MemoryVectors


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
        assert "memory_error_code" not in response.json()
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
        assert initialize(database) == initialize(database) == 14
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


def test_author_chunks_keep_questions_and_offsets_without_vector_configuration(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        template = client.get("/api/character-authoring/template").json()
        questions = [
            dict(
                question_id=item["id"],
                question=item["question"],
                answer="我喜欢晴天，在青石镇修理旧钟。" * 70,
            )
            for item in template["interview"][:10]
        ]
        draft, _ = create_draft(client, story="在青石镇长大。\n\n" * 120, interview=questions)
        blueprint, _ = confirm(client, draft)
        response = client.post(
            "/api/communities/community/characters",
            json=dict(
                player_id="alice", blueprint_id=blueprint["blueprint_id"], character_id="chunks"
            ),
        )
        assert response.status_code == 201, response.text
        application = client.app.state.application
        assert application.embeddings is None
        assert "memory-vectors" not in application.supervisor.workers
        with application.database.transaction() as connection:
            service = MemoryMaterials(SearchRepository())
            service.authors(connection, "community", "chunks", datetime.now(UTC))
            service.authors(connection, "community", "chunks", datetime.now(UTC))
        retrieval = application.planner.tasks.context.retrieval
        with application.database.read() as connection:
            rows = connection.execute(
                "SELECT c.*,m.content AS original,m.question FROM memory_author_chunks c "
                "JOIN memory_author_materials m USING(material_id) WHERE m.character_id='chunks'"
            ).fetchall()
            assert all(
                row["content"] == row["original"][row["start_offset"] : row["end_offset"]]
                and len(row["content"]) <= 800
                for row in rows
            )
            hits = retrieval.search(
                connection, SearchScope("community", "chunks", datetime.now(UTC)), "青石镇"
            )
            assert hits and all(hit.source_kind == "author_chunk" for hit in hits)
            interview = [
                hit
                for hit in retrieval.sources(
                    connection, SearchScope("community", "chunks", datetime.now(UTC))
                ).values()
                if hit.memory_kind == "interview"
            ]
            assert interview and all(
                hit.text.splitlines()[0] in {item["question"] for item in questions}
                for hit in interview
            )
        content = "甲" * 2500
        ranges = chunk_ranges(content)
        covered = set().union(*(set(range(start, end)) for start, end in ranges))
        assert covered == set(range(len(content)))


def test_vector_configuration_failure_is_persisted_and_fulltext_remains_usable(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    memory = settings.memory.model_copy(
        update={
            "vector": settings.memory.vector.model_copy(
                update={"enabled": True, "profile": "missing-embedding"}
            )
        }
    )
    with TestClient(create_app(settings.model_copy(update={"memory": memory}))) as client:
        create_group(client)
        application = client.app.state.application
        vectors = application.supervisor.workers["memory-vectors"]
        assert not asyncio.run(vectors.run_once())
        with application.database.read() as connection:
            failures = [
                dict(row) for row in connection.execute("SELECT * FROM memory_vector_failures")
            ]
            assert failures and all(row["provider_attempts"] == 0 for row in failures)
        assert not asyncio.run(
            MemoryVectors(application.database, application.embeddings).run_once()
        )
        with application.database.read() as connection:
            assert [
                dict(row) for row in connection.execute("SELECT * FROM memory_vector_failures")
            ] == failures
        response = client.post(
            "/api/conversations/conversation/messages",
            json=dict(
                player_id="alice", client_message_id="vector-query", text="你喜欢整理香草吗？"
            ),
        )
        assert response.status_code == 202, response.text
        application.planner.plan()
        assert asyncio.run(application.queue.claim("before-search", datetime.now(UTC))) is None
        worker = application.supervisor.workers["conversation-memory"]
        assert asyncio.run(worker.run_once())
        lease = asyncio.run(application.queue.claim("after-search", datetime.now(UTC)))
        assert lease is not None
        snapshot = application.handler.execution.prepare(
            lease.task_id, attempt=lease.attempt
        ).invocation.context
        assert snapshot.memory.retrieval_prepared
        assert application.embeddings._client is None
        index_url = "/internal/characters/first/memory-index?community_id=community"
        status = client.get(index_url)
        assert status.status_code == 200 and status.json()["failures"]
        rebuilt = client.post(
            "/internal/characters/first/memory-index/rebuild?community_id=community"
        )
        assert rebuilt.status_code == 200 and rebuilt.json()["failures"] == []


def test_simple_summary_search_is_automatically_frozen_across_conversations(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client, memory_mode="simple")
        application = client.app.state.application
        response = client.post(
            "/api/conversations/conversation/messages",
            json=dict(
                player_id="alice",
                client_message_id="old-promise",
                text="我们约定明天一起修理蓝风铃。",
            ),
        )
        assert response.status_code == 202, response.text
        segment = application.memory_sealing.seal("community", "first", "conversation")
        with application.database.transaction() as connection:
            MemoryIngestion(SegmentRepository(), CoverageRepository()).ingest(
                connection,
                "community",
                "first",
                segment.segment_id,
                "爱丽丝和我约定明天一起修理蓝风铃。",
                datetime.now(UTC),
            )
        response = client.post(
            "/api/communities/community/conversations",
            json=dict(
                player_id="alice",
                kind="direct",
                conversation_id="new-conversation",
                actors=[
                    dict(kind="player", actor_id="alice"),
                    dict(kind="character", actor_id="first"),
                ],
            ),
        )
        assert response.status_code == 201, response.text
        client.post(
            "/api/conversations/new-conversation/messages",
            json=dict(player_id="alice", client_message_id="remind", text="你记得蓝风铃的约定吗？"),
        )
        application.planner.plan()
        with application.database.read() as connection:
            row = connection.execute(
                "SELECT task_id FROM conversation_tasks WHERE conversation_id='new-conversation'"
            ).fetchone()
            snapshot = application.conversation_diagnostics.tasks.snapshot(connection, row[0])
            assert any(
                item.source_kind == "segment_summary" and item.memory_id == segment.segment_id
                for item in snapshot.memory.recalled
            )
            original = snapshot.model_dump_json()
        client.post(
            "/api/conversations/new-conversation/messages",
            json=dict(
                player_id="alice",
                client_message_id="future",
                text="未来的新内容不能进入之前的输入。",
            ),
        )
        with application.database.read() as connection:
            assert (
                application.conversation_diagnostics.tasks.snapshot(
                    connection, row[0]
                ).model_dump_json()
                == original
            )


def test_waiting_model_budget_prioritizes_chat_without_interrupting_active_work(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        budget = ModelBudget(client.app.state.application.gateway, 1)

        async def run():
            entered = []
            ready = asyncio.Event()
            release = asyncio.Event()

            async def active():
                async with budget.slot(2):
                    entered.append("active")
                    ready.set()
                    await release.wait()

            async def waiting(name, priority):
                async with budget.slot(priority):
                    entered.append(name)

            active_task = asyncio.create_task(active())
            await ready.wait()
            background = asyncio.create_task(waiting("background", 2))
            chat = asyncio.create_task(waiting("chat", 0))
            await asyncio.sleep(0)
            release.set()
            await asyncio.gather(active_task, background, chat)
            assert entered == ["active", "chat", "background"]

        asyncio.run(run())
