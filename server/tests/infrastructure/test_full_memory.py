import asyncio
import json
from datetime import UTC, datetime

import pytest
from capture_assertions import assert_readable_model_calls
from fastapi.testclient import TestClient
from test_application_lifecycle import settings_for
from test_character_authoring import confirm, create_draft
from test_http_api import create_group

from echo_commons.agents.contracts.context import MemoryContext
from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.app.main import create_app
from echo_commons.execution.contracts import Disposition
from echo_commons.execution.recovery import decision
from echo_commons.modules.characters.domain.changes import RelationshipChange, StateChange
from echo_commons.modules.characters.domain.relationship import (
    RelationshipDimension,
    RelationshipDirection,
    RelationshipEvidenceKind,
    RelationshipKey,
)
from echo_commons.modules.characters.domain.state import StateKind
from echo_commons.modules.memory.domain.organization import (
    FactAdd,
    MemoryFactContent,
    OrganizationEvidence,
)
from echo_commons.modules.memory.domain.summaries import SummaryConsumer
from echo_commons.modules.memory.repositories.author_batches import AuthorBatchRepository
from echo_commons.modules.memory.repositories.changes import MemoryChangeRepository
from echo_commons.modules.memory.repositories.relationship_evidence import (
    RelationshipEvidenceReader,
)
from echo_commons.modules.memory.services.retrieval import SearchScope
from echo_commons.modules.memory.services.view_materials import ViewMaterialPreparation
from echo_commons.modules.reflection.contexts.sources import ReflectionSourceUnavailable
from echo_commons.modules.reflection.contracts.candidates import RelationshipDimensionAction
from echo_commons.shared.actors import ActorRef


def create_authored(client):
    create_group(client)
    draft, _ = create_draft(
        client,
        story=(
            "小时候住在青石镇，外婆教我修理旧钟。外婆留下的铜钥匙一直保存在我的抽屉里。"
            "我习惯每周末擦拭钟表，喜欢阴凉安静的房间。"
        ),
    )
    blueprint, _ = confirm(client, draft)
    response = client.post(
        "/api/communities/community/characters",
        json=dict(
            player_id="alice",
            blueprint_id=blueprint["blueprint_id"],
            character_id="authored",
            memory_mode="full",
        ),
    )
    assert response.status_code == 201, response.text
    app = client.app.state.application
    assert app.supervisor.workers["memory-preparation"].prepare_materials()
    assert app.supervisor.workers["memory-initialization"].advance()
    return app


def test_memory_metadata_and_relationship_evidence_have_explicit_shapes():
    memory = dict(
        resident=[dict(memory_id="clock", content_version="1", content="外婆留下的旧钟。")],
        recalled=[],
        session_digest="",
        history_thoughts=[],
        segment_summaries=[],
    )
    assert MemoryContext.model_validate(memory).model_dump(mode="json") == memory
    relation = dict(
        target=dict(kind="player", actor_id="alice"),
        dimension="trust",
        direction="positive",
        level=1,
        evidence_refs=["message:original"],
    )
    assert RelationshipDimensionAction.model_validate(relation).model_dump(mode="json") == relation


def test_author_batch_is_frozen_without_conversation_or_player_relations(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        app = create_authored(client)
        with app.database.read() as connection:
            row = connection.execute(
                "SELECT * FROM memory_initializations WHERE character_id='authored'"
            ).fetchone()
            snapshot = app.reflection.runs.snapshot(
                connection, "community", "authored", row["organization_run_id"]
            )
            assert not snapshot.conversations
            assert snapshot.source_kind == "author_material_batch"
            assert all(item.kind == "author_chunk" for item in snapshot.materials)
            assert snapshot.self.relationships == ()
            app.reflection.context.sources.check_sources(connection, snapshot)
        assert not app.supervisor.workers["memory-initialization"].advance()
        inspected = client.get(
            f"/internal/reflection/runs/{row['organization_run_id']}",
            params=dict(community_id="community", character_id="authored"),
        )
        assert inspected.status_code == 200, inspected.text
        body = inspected.json()
        assert body["snapshot"]["materials"][0]["kind"] == "author_chunk"
        assert body["supplement"] is None and body["supplement_run_ids"] == []
        node_id = next(
            node["task_id"] for node in body["node_tasks"] if node["node_key"] == "fact_extract"
        )
        node_input = client.get(
            f"/internal/reflection/runs/{row['organization_run_id']}/nodes/{node_id}/input",
            params=dict(community_id="community", character_id="authored"),
        )
        assert node_input.status_code == 200, node_input.text
        materials = node_input.json()["input"]["graph_snapshot"]["materials"]
        assert materials[0]["kind"] == "author_chunk"


def test_full_search_returns_matching_pages_without_entity_expansion(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        app = create_authored(client)
        with app.database.transaction() as connection:
            identity = connection.execute("SELECT batch_id FROM memory_author_batches").fetchone()[
                0
            ]
            repository = AuthorBatchRepository()
            batch = repository.get(connection, "community", "authored", identity)
            material = repository.materials(connection, batch)[0]
            source = OrganizationEvidence(
                kind="author_chunk",
                source_id=material["chunk_id"],
                version=material["blueprint_version"],
            )
            app.reflection_graph_commit.facts.organization.organize(
                connection,
                "community",
                "authored",
                batch.batch_id,
                tuple(
                    FactAdd(
                        local_key=f"fact{index}",
                        fact=MemoryFactContent(topic="童年", content=text),
                        evidence_refs=(f"author_chunk:{source.source_id}",),
                    )
                    for index, text in enumerate(
                        (
                            "我小时候住在青石镇。",
                            "外婆教会我修理旧钟。",
                            "铜钥匙一直保存在抽屉里。",
                        ),
                        1,
                    )
                ),
                (),
                (source,),
                True,
                datetime.now(UTC),
                datetime.now(UTC),
            )
        with app.database.read() as connection:
            hits = app.planner.tasks.context.retrieval.search(
                connection,
                SearchScope("community", "authored", datetime.now(UTC)),
                "青石镇",
                limit=5,
            )
            assert any("青石镇" in item.text for item in hits)
            page_hits = [item for item in hits if item.source_kind == "memory_fact"]
            assert not any(
                "铜钥匙一直" in item.text or "外婆教会" in item.text for item in page_hits
            )
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
        pages = client.get("/internal/communities/community/characters/authored/memory/facts")
        assert pages.status_code == 200, pages.text
        page = pages.json()["items"][0]
        detail = client.get(
            f"/internal/communities/community/characters/authored/memory/facts/{page['memory_id']}",
        )
        assert detail.status_code == 200, detail.text
        assert detail.json()["sources"][0]["readable"] is True
        assert "entities" not in detail.json()
        for collection in ("entities", "edges"):
            assert (
                client.get(
                    f"/internal/communities/community/characters/authored/memory/{collection}",
                ).status_code
                == 422
            )


def test_partial_view_supplement_reuses_runtime_plan_and_only_retries_cancelled_branch(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        receipt = client.post(
            "/api/conversations/conversation/messages",
            json=dict(
                player_id="alice", client_message_id="repair", text="今天修好了旧钟，心情放松了。"
            ),
        )
        assert receipt.status_code == 202
        app = client.app.state.application
        with app.database.transaction() as connection:
            app.reflection_graph_commit.facts.characters.apply(
                connection,
                "community",
                "first",
                "message",
                receipt.json()["message_id"],
                (),
                (StateChange(StateKind.MOOD, "放松"),),
                datetime.now(UTC),
            )
        assert app.supervisor.workers["memory-views"].scan()

        async def cancel_branch():
            queue = app.reflection_queue
            handler = app.supervisor.workers["reflection-0"].dispatcher.registry.resolve(
                "reflection"
            )
            planner = await queue.claim("view-plan", datetime.now(UTC))
            assert (await handler.execute(planner)).disposition == Disposition.COMPLETED
            branch = await queue.claim("view-cancel", datetime.now(UTC))
            with app.database.read() as connection:
                node = queue.nodes.get(connection, branch.task_id)
                assert node.node_key == "state_summary_view"
            assert await queue.apply_recovery(
                branch,
                datetime.now(UTC),
                decision("execution_cancelled", FailureCategory.HARNESS, RecoveryAction.FAIL),
            )
            aggregate = await queue.claim("view-aggregate", datetime.now(UTC))
            assert (await handler.execute(aggregate)).disposition == Disposition.COMPLETED
            return node.graph_run_id

        original = client.portal.call(cancel_branch)
        child = app.reflection.restart("community", "first", str(original))
        assert child.graph_run_id != original
        params = dict(community_id="community", character_id="first")
        original_detail = client.get(f"/internal/reflection/runs/{original}", params=params)
        assert original_detail.status_code == 200, original_detail.text
        assert original_detail.json()["supplement_run_ids"] == [str(child.graph_run_id)]
        child_detail = client.get(f"/internal/reflection/runs/{child.graph_run_id}", params=params)
        assert child_detail.status_code == 200, child_detail.text
        assert child_detail.json()["supplement"] == dict(
            original_run_id=str(original), retry_node_keys=["state_summary_view"]
        )
        assert child_detail.json()["snapshot"]["materials"][0]["kind"] == "formal_fact"
        assert (
            app.reflection.restart("community", "first", str(original)).graph_run_id
            == child.graph_run_id
        )
        with app.database.read() as connection:
            nodes = app.reflection.nodes.for_graph(connection, str(child.graph_run_id))
            planner = next(item for item in nodes if item.node_key == "view_refresh_planner")
            branch = next(item for item in nodes if item.node_key == "state_summary_view")
            assert planner.status == "completed" and planner.attempt_count == 0
            assert branch.status == "pending" and branch.activated
            assert all(
                item.status == "skipped"
                for item in nodes
                if item.node_key in ("core_memory_view", "relationship_attitude_view")
            )
            assert connection.execute("SELECT COUNT(*) FROM memory_views").fetchone()[0] == 0
            assert app.gateway._clients == {}
        node_input = client.get(
            f"/internal/reflection/runs/{child.graph_run_id}/nodes/{branch.task_id}/input",
            params=params,
        )
        assert node_input.status_code == 200, node_input.text
        assert node_input.json()["input"]["graph_snapshot"]["materials"][0]["kind"] == "formal_fact"


def test_author_budget_failure_preserves_materials_and_can_retry(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"reflection_max_material_chars": 1}
    )
    with TestClient(create_app(settings)) as client:
        app = create_authored(client)
        with app.database.read() as connection:
            instance = app.characters.instances.get(connection, "community", "authored")
            assert instance.memory_status == "failed"
            assert instance.memory_error_code == "author_material_budget_exceeded"
            assert (
                connection.execute("SELECT COUNT(*) FROM memory_author_batches").fetchone()[0] == 0
            )
            assert connection.execute("SELECT COUNT(*) FROM memory_author_chunks").fetchone()[0] > 0
        app.reflection.context.graph.policy = app.reflection.context.graph.policy.__class__(
            frozenset(), 8, 256, 20000
        )
        app.characters.retry_memory("community", "authored", player_id="alice")
        assert app.supervisor.workers["memory-initialization"].advance()
        with app.database.read() as connection:
            assert (
                app.characters.instances.get(connection, "community", "authored").memory_status
                == "preparing"
            )


def test_view_source_change_requires_fresh_current_facts(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        app = client.app.state.application
        writer = app.reflection_graph_commit.facts.characters

        def record(text):
            message = client.post(
                "/api/conversations/conversation/messages",
                json=dict(player_id="alice", client_message_id=text, text=text),
            ).json()
            with app.database.transaction() as connection:
                writer.apply(
                    connection,
                    "community",
                    "first",
                    "message",
                    message["message_id"],
                    (),
                    (StateChange(StateKind.MOOD, text),),
                    datetime.now(UTC),
                )

        record("平静")
        assert app.supervisor.workers["memory-views"].scan()
        with app.database.read() as connection:
            run_id = connection.execute(
                "SELECT graph_run_id FROM reflection_graph_runs WHERE graph_kind='view_refresh'"
            ).fetchone()[0]
            old = app.reflection.runs.snapshot(connection, "community", "first", run_id)
        record("高兴")
        with app.database.transaction() as connection:
            with pytest.raises(ReflectionSourceUnavailable):
                app.reflection.context.sources.check_sources(connection, old)
            repository = MemoryChangeRepository()
            repository.supersede(connection, old, datetime.now(UTC))
            batch = ViewMaterialPreparation().freeze(
                connection,
                repository,
                "community",
                "first",
                datetime.now(UTC),
                max_count=256,
                max_chars=20000,
            )
            assert "高兴" in batch["materials_json"] and "平静" not in batch["materials_json"]


def test_relationship_view_keeps_real_evidence_ids_and_separate_targets(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        app = client.app.state.application
        source = client.post(
            "/api/conversations/conversation/messages",
            json=dict(
                player_id="alice",
                client_message_id="support",
                text="我帮你修钟，bob答应周末来帮忙。",
            ),
        )
        assert source.status_code == 202
        now = datetime.now(UTC)
        writer = app.reflection_graph_commit.facts.characters
        with app.database.transaction() as connection:
            writer.apply(
                connection,
                "community",
                "first",
                "message",
                source.json()["message_id"],
                (
                    RelationshipChange(
                        ActorRef("player", "alice"),
                        RelationshipDimension.TRUST,
                        RelationshipDirection.UP,
                        1,
                        now,
                        RelationshipEvidenceKind.SUPPORT,
                    ),
                    RelationshipChange(
                        ActorRef("player", "bob"),
                        RelationshipDimension.TRUST,
                        RelationshipDirection.UP,
                        1,
                        now,
                        RelationshipEvidenceKind.COMMITMENT,
                    ),
                ),
                (),
                now,
            )
        assert app.supervisor.workers["memory-views"].scan()
        with app.database.transaction() as connection:
            batch = connection.execute("SELECT * FROM memory_change_batches").fetchone()
            facts = json.loads(batch["materials_json"])
            relation = json.loads(facts[0]["content"])
            assert relation["target_id"] == "alice"
            assert len(relation["evidence"]) == 1
            assert (
                "发送者：player:alice\n我帮你修钟，bob答应周末来帮忙。"
                in relation["evidence"][0]["content"]
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM memory_changes WHERE batch_id IS NULL"
                ).fetchone()[0]
                == 1
            )
            writer.refresh_attitude(
                connection,
                "community",
                "first",
                ActorRef("player", "alice"),
                "愿意信任这个实际帮助过我的人。",
                datetime.now(UTC),
                datetime.now(UTC),
                evidence_ids=tuple(item["evidence_id"] for item in relation["evidence"]),
            )
            state = writer.relationships.get(
                connection,
                RelationshipKey("community", "first", "player", "alice"),
                datetime.now(UTC),
            )
            assert state.attitude_summary and state.attitude_source_refs
            assert {str(item) for item in state.attitude_source_refs} == {
                item["evidence_id"] for item in relation["evidence"]
            }
            assert all(
                connection.execute(
                    "SELECT 1 FROM relation_evidence WHERE evidence_id=?", (str(identity),)
                ).fetchone()
                for identity in state.attitude_source_refs
            )


def test_relationship_view_reads_owned_segment_summary_within_material_budget(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        app = client.app.state.application
        response = client.post(
            "/api/conversations/conversation/messages",
            json=dict(player_id="alice", client_message_id="help", text="我帮你把旧钟修好了。"),
        )
        assert response.status_code == 202
        segment = app.memory_sealing.seal("community", "first")
        now = datetime.now(UTC)
        summary = "对方帮我修好了旧钟，我觉得他很可靠。"
        original_sources = tuple(
            (source.kind.value, source.source_id, source.version) for source in segment.sources
        )
        with app.database.transaction() as connection:
            app.reflection_graph_commit.facts.memory.ingest(
                connection, "community", "first", segment.segment_id, summary, now
            )
            app.reflection_graph_commit.facts.characters.apply(
                connection,
                "community",
                "first",
                "memory_segment",
                segment.segment_id,
                (
                    RelationshipChange(
                        ActorRef("player", "alice"),
                        RelationshipDimension.TRUST,
                        RelationshipDirection.UP,
                        1,
                        now,
                        RelationshipEvidenceKind.SUPPORT,
                        sources=original_sources,
                    ),
                ),
                (),
                now,
            )
            assert (
                RelationshipEvidenceReader().read(
                    connection, "community", "first", "player", "alice", now, 1
                )
                == []
            )
            batch = ViewMaterialPreparation().freeze(
                connection,
                MemoryChangeRepository(),
                "community",
                "first",
                now,
                max_count=256,
                max_chars=20000,
            )
            relation = json.loads(json.loads(batch["materials_json"])[0]["content"])
            assert "我帮你把旧钟修好了。" in relation["evidence"][0]["content"]
            assert summary not in relation["evidence"][0]["content"]
            assert relation["evidence"][0]["source_ref"] == segment.segment_id


@pytest.mark.model
def test_real_relationship_view_uses_frozen_evidence_without_changing_scores(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"debug_capture_enabled": True, "debug_capture_path": str(tmp_path / "capture")}
    )
    with TestClient(create_app(settings)) as client:
        create_group(client)
        app = client.app.state.application
        receipt = client.post(
            "/api/conversations/conversation/messages",
            json=dict(player_id="alice", client_message_id="clock", text="我已经帮你修好了旧钟。"),
        )
        assert receipt.status_code == 202
        now = datetime.now(UTC)
        key = RelationshipKey("community", "first", "player", "alice")
        writer = app.reflection_graph_commit.facts.characters
        with app.database.transaction() as connection:
            writer.apply(
                connection,
                "community",
                "first",
                "message",
                receipt.json()["message_id"],
                (
                    RelationshipChange(
                        ActorRef("player", "alice"),
                        RelationshipDimension.TRUST,
                        RelationshipDirection.UP,
                        1,
                        now,
                        RelationshipEvidenceKind.SUPPORT,
                    ),
                ),
                (),
                now,
            )
            before = writer.relationships.get(connection, key, now)
        assert app.supervisor.workers["memory-views"].scan()

        async def finish():
            async with asyncio.timeout(240):
                while lease := await app.reflection_queue.claim(
                    "attitude-check", datetime.now(UTC)
                ):
                    outcome = (
                        await app.supervisor.workers["reflection-0"]
                        .dispatcher.registry.resolve("reflection")
                        .execute(lease)
                    )
                    assert outcome.disposition == Disposition.COMPLETED, outcome

        client.portal.call(finish)
        with app.database.read() as connection:
            after = writer.relationships.get(connection, key, datetime.now(UTC))
            assert after.values == before.values and after.state_version == before.state_version
            assert after.attitude_summary.strip()
            batch = connection.execute("SELECT * FROM memory_change_batches").fetchone()
            fact = json.loads(json.loads(batch["materials_json"])[0]["content"])
            assert {str(item) for item in after.attitude_source_refs} == {
                item["evidence_id"] for item in fact["evidence"]
            }
            assert "修好了旧钟" in fact["evidence"][0]["content"]
        calls = list((tmp_path / "capture").glob("*/*-model_call.json"))
        assert calls
        assert_readable_model_calls(calls[0].parent)
        for path in calls:
            request = json.loads(path.read_text(encoding="utf-8"))["input"]["modelRequest"]
            prompt = "\n".join(message["content"] for message in request["messages"])
            assert "affection（好感）" in prompt and "attachment（依恋）" in prompt
            assert "修好了旧钟" in prompt and "你正在整理当前角色可以知道的材料。" in prompt


@pytest.mark.model
def test_real_simple_summary_and_compression_keep_only_simple_consumers(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client, memory_mode="simple")
        response = client.post(
            "/api/conversations/conversation/messages",
            json=dict(
                player_id="alice",
                client_message_id="promise",
                text="我们约定周末一起修理蓝风铃，请记住这个约定。",
            ),
        )
        assert response.status_code == 202
        app = client.app.state.application
        segment = app.memory_sealing.seal("community", "first")
        app.reflection_workflow.schedule_segment("community", "first", segment.segment_id)

        async def execute_pending():
            async with asyncio.timeout(240):
                while lease := await app.reflection_queue.claim("simple-check", datetime.now(UTC)):
                    outcome = (
                        await app.supervisor.workers["reflection-0"]
                        .dispatcher.registry.resolve("reflection")
                        .execute(lease)
                    )
                    assert outcome.disposition == Disposition.COMPLETED, outcome

        client.portal.call(execute_pending)
        assert app.reflection_workflow.schedule_summaries(
            "community",
            "first",
            SummaryConsumer.CONTINUITY,
        )
        client.portal.call(execute_pending)
        with app.database.read() as connection:
            hits = app.planner.tasks.context.retrieval.search(
                connection,
                SearchScope("community", "first", datetime.now(UTC)),
                "蓝风铃",
                limit=5,
            )
            assert any(item.source_kind == "segment_summary" for item in hits)
            assert (
                connection.execute("SELECT COUNT(*) FROM conversation_digests").fetchone()[0] == 1
            )
            assert connection.execute("SELECT COUNT(*) FROM memory_views").fetchone()[0] == 0
            kinds = connection.execute("SELECT graph_kind FROM reflection_graph_runs").fetchall()
            assert {row[0] for row in kinds} == {"segment_reflect", "continuity_compress"}
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


@pytest.mark.model
def test_real_author_organization_and_core_view_complete_initialization(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"debug_capture_enabled": True, "debug_capture_path": str(tmp_path / "capture")}
    )
    with TestClient(create_app(settings)) as client:
        app = create_authored(client)

        async def finish():
            async with asyncio.timeout(240):
                for _ in range(20):
                    lease = await app.reflection_queue.claim("full-memory-check", datetime.now(UTC))
                    if lease:
                        outcome = (
                            await app.supervisor.workers["reflection-0"]
                            .dispatcher.registry.resolve("reflection")
                            .execute(lease)
                        )
                        assert outcome.disposition == Disposition.COMPLETED, outcome
                    app.supervisor.workers["memory-initialization"].advance()
                    app.supervisor.workers["memory-views"].scan()
                    with app.database.read() as connection:
                        instance = app.characters.instances.get(connection, "community", "authored")
                    if instance.memory_status == "ready":
                        return
                pytest.fail("Full initialization did not finish")

        client.portal.call(finish)
        with app.database.read() as connection:
            pages = connection.execute(
                "SELECT * FROM memory_facts WHERE character_id='authored'"
            ).fetchall()
            assert pages and all(row["source_kind"] == "author_material_batch" for row in pages)
            provenance = app.reflection_graph_commit.facts.organization.provenance
            for page in pages:
                sources = provenance.record_sources(
                    connection, "community", "authored", "fact", page["memory_id"], page["version"]
                )
                assert sources and all(source["readable"] for source in sources)
            run_id = connection.execute(
                "SELECT organization_run_id FROM memory_initializations "
                "WHERE character_id='authored'"
            ).fetchone()[0]
            run = app.reflection.runs.get(connection, "community", "authored", run_id)
            assert run.graph_version == "v5"
            assert {
                node.node_key for node in app.reflection.nodes.for_graph(connection, run_id)
            } == {
                "fact_extract",
                "fact_review",
                "cognition_reflect",
                "memory_aggregate",
            }
            core = connection.execute(
                "SELECT * FROM memory_views WHERE character_id='authored' "
                "AND view_kind='core_memory'"
            ).fetchone()
            assert core and core["content"].strip()
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM relationship_state WHERE observer_character_id='authored'"
                ).fetchone()[0]
                == 0
            )
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
