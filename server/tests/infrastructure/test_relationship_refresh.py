import asyncio
import json
import time
from dataclasses import replace
from uuid import uuid4

import pytest
from fastapi.testclient import TestClient
from support.application import settings_for
from support.http import create_group
from support.migrations import load_history

from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.characters.domain.changes import RelationshipChange
from echo_commons.modules.memory.repositories.changes import MemoryChangeRepository
from echo_commons.modules.memory.services.view_materials import ViewMaterialPreparation
from echo_commons.modules.reflection.contracts.candidates import (
    ReflectionBatchProposal,
    ReflectionNodeAction,
)
from echo_commons.modules.reflection.contracts.context import REFLECTION_NODE_CONTRACT, FactMaterial
from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind
from echo_commons.modules.reflection.tasks.graph_review import GraphReview
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.prompt import project_node
from echo_commons.modules.reflection.views import ViewScheduling
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError

URL = "/internal/communities/community/characters/first/reflection/relationship-attitudes"
RELATIONS = "/internal/communities/community/characters/first/relationships"


def interaction(client, target="alice", *, direction="neutral", text="你好，我叫 Alice。"):
    response = client.post(
        "/api/conversations/conversation/messages",
        json={"player_id": target, "client_message_id": str(uuid4()), "text": text},
    )
    assert response.status_code == 202, response.text
    application = client.app.state.application
    with application.database.transaction() as connection:
        now = utc_now()
        application.reflection_graph_commit.facts.characters.apply(
            connection,
            "community",
            "first",
            "message",
            response.json()["message_id"],
            (
                RelationshipChange(
                    ActorRef("player", target),
                    "affection",
                    direction,
                    0 if direction == "neutral" else 2,
                    now,
                ),
            ),
            (),
            now,
        )
    return response.json()["message_id"]


def request_refresh(client, target=None, request_id=None):
    body = {"request_id": request_id or str(uuid4())}
    if target:
        body["target"] = {"kind": "player", "actor_id": target}
    response = client.post(URL, json=body)
    assert response.status_code == 202, response.text
    return response.json()


def test_refresh_freezes_target_voice_evidence_and_idempotent_scope(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        interaction(client)
        identity = str(uuid4())
        rows = request_refresh(client, "alice", identity)
        assert request_refresh(client, "alice", identity) == rows
        assert client.post(URL, json={"request_id": identity}).status_code == 409
        app = client.app.state.application
        with app.database.read() as connection:
            snapshot = app.reflection.runs.snapshot(
                connection,
                "community",
                "first",
                rows[0]["graph_run_id"],
            )
            fact = json.loads(snapshot.materials[0].content)
            assert fact["initial_description"] and fact["previous_attitude"] == ""
            assert fact["target_name"] == "alice" and fact["observer_name"] == "小槿"
            assert (fact["affection"], fact["trust"], fact["attachment"]) == (50, 50, 0)
            assert fact["evidence"][0]["content_status"] == "readable"
            assert "你好" in fact["evidence"][0]["content"]
            batch = MemoryChangeRepository().get(
                connection, "community", "first", snapshot.source_id
            )
            materials = tuple(
                FactMaterial.model_validate(item) for item in json.loads(batch["materials_json"])
            )
            graph = app.reflection.context.graph
            graph.policy = replace(
                graph.policy, max_material_chars=sum(len(item.content) for item in materials)
            )
            prepared = graph.prepare(
                connection,
                "community",
                "first",
                snapshot.graph_kind,
                snapshot.source_kind,
                snapshot.source_id,
                snapshot.source_version,
                materials,
                utc_now(),
            )
            assert json.loads(prepared.materials[0].content)["target_name"] == "alice"
        node = prepare_node_input(
            snapshot,
            graph_run_id=rows[0]["graph_run_id"],
            node_task_id="projection",
            node_key="relationship_attitude_view",
            node_kind=ReflectionNodeKind.RELATIONSHIP_ATTITUDE_VIEW,
        )
        outputs = OutputRegistry()
        outputs.register(REFLECTION_NODE_CONTRACT, ReflectionNodeAction)
        prompt = project_node(
            node,
            output_contract=REFLECTION_NODE_CONTRACT,
            outputs=outputs,
            max_content_chars=123,
        )
        text = "\n".join(message.content for message in prompt.messages)
        assert "<character_voice>" in text and "alice" in text
        assert "最多 123 字符" in text and "initial_description=true" in text
        assert client.get(RELATIONS).json()["items"][0]["attitude_refresh"]["graph_run_id"]


def test_new_neutral_evidence_invalidates_frozen_relation_without_changing_scores(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        interaction(client)
        run = request_refresh(client, "alice")[0]["graph_run_id"]
        app = client.app.state.application
        with app.database.read() as connection:
            snapshot = app.reflection.runs.snapshot(connection, "community", "first", run)
            MemoryChangeRepository().check(connection, snapshot)
        interaction(client, text="我今天想看看这里的书。")
        with app.database.read() as connection:
            with pytest.raises(ConflictError, match="evidence changed"):
                MemoryChangeRepository().check(connection, snapshot)
            changes = MemoryChangeRepository().pending(connection, "community", "first")
            assert len([row for row in changes if row["fact_kind"] == "relationship"]) == 2
        relation = client.get(RELATIONS).json()["items"][0]
        assert (relation["affection"], relation["trust"], relation["attachment"]) == (50, 50, 0)
        assert relation["state_version"] == 1


def test_missing_repair_is_once_per_source_and_distinguishes_unreadable_text(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        interaction(client)
        app = client.app.state.application
        with app.database.transaction() as connection:
            changes = MemoryChangeRepository()
            preparation = ViewMaterialPreparation()
            batch = preparation.freeze(
                connection, changes, "community", "first", utc_now(), max_count=256, max_chars=20000
            )
            assert batch
            # 原消息真实存在，但撤销观察资格后正文不可读取。
            connection.execute(
                "UPDATE conversation_memberships SET joined_after_sequence=999 "
                "WHERE conversation_id='conversation' AND actor_id='first'"
            )
            fact = next(
                item
                for item in changes.facts(connection, "community", "first", utc_now())
                if item["fact_kind"] == "relationship"
            )
            material = preparation.relationship(
                connection, "community", "first", fact, utc_now(), 20000
            )
            evidence = json.loads(material["content"])["evidence"]
            assert evidence[0]["content_status"] == "unavailable"
            assert evidence[0]["evidence_id"] and evidence[0]["content"] == ""
            assert (
                preparation.freeze(
                    connection,
                    changes,
                    "community",
                    "first",
                    utc_now(),
                    max_count=256,
                    max_chars=20000,
                )
                is None
            )


def test_no_evidence_diagnostic_and_stranger_rejection(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        assert client.post(URL, json={"request_id": str(uuid4())}).status_code == 409
        interaction(client)
        app = client.app.state.application
        with app.database.transaction() as connection:
            connection.execute(
                "DELETE FROM relation_evidence_sources WHERE evidence_id IN "
                "(SELECT evidence_id FROM relation_evidence WHERE observer_character_id='first')"
            )
            connection.execute("DELETE FROM relation_evidence WHERE observer_character_id='first'")
        rows = request_refresh(client, "alice")
        assert rows[0]["graph_run_id"] is None
        assert rows[0]["error_code"] == "relationship_evidence_missing"
        assert client.get(RELATIONS).json()["items"][0]["attitude_refresh"]["error_code"]


def test_first_description_no_op_requires_bounded_repair(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        interaction(client)
        run = request_refresh(client, "alice")[0]["graph_run_id"]
        app = client.app.state.application
        with app.database.read() as connection:
            snapshot = app.reflection.runs.snapshot(connection, "community", "first", run)
        proposal = ReflectionBatchProposal(outcome="no_op", no_op_reason="没有显著数值变化")
        code = GraphReview(64, 20000).check(snapshot, proposal)
        assert code == "reflection_relationship_description_required"
        decision = app.reflection_queue.recovery.review(code)
        assert decision.failure.repair_hint and decision.action.value == "retry_task"


async def finish_relation(app, graph_id, success=True):
    dispatcher = app.supervisor.workers["reflection-0"].dispatcher
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        with app.database.read() as connection:
            run = app.reflection.runs.get(connection, "community", "first", graph_id)
        if run.is_terminal:
            if success:
                assert run.status == "completed", run
            return run
        lease = await app.reflection_queue.claim(dispatcher.owner, utc_now())
        if lease:
            await dispatcher._execute(lease)
        else:
            await asyncio.sleep(0.1)
    raise TimeoutError("Relationship refresh did not finish")


def test_real_provider_failure_does_not_block_second_target(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"model_secrets_path": str(tmp_path / "absent.toml")},
    )
    with TestClient(create_app(settings)) as client:
        create_group(client)
        interaction(client)
        interaction(client, "bob", text="大家好，我叫 Bob。")
        app = client.app.state.application
        scheduling = ViewScheduling(app.reflection)
        assert scheduling.scan()
        first = client.get(RELATIONS).json()["items"][0]["attitude_refresh"]["graph_run_id"]
        run = client.portal.call(finish_relation, app, first, False)
        assert run.status in ("failed", "partial")
        assert scheduling.scan()
        second = client.get(RELATIONS).json()["items"][1]["attitude_refresh"]["graph_run_id"]
        assert second and second != first
        client.portal.call(finish_relation, app, second, False)
        assert not scheduling.scan()
        interaction(client, text="我又过来看看书。")
        assert scheduling.scan()


def test_version_fifteen_failed_target_gets_one_missing_repair(tmp_path):
    historical = load_history(15, tmp_path / "historical.sqlite3")
    initialize(historical)
    with historical.transaction() as connection:
        preparation = ViewMaterialPreparation()
        changes = MemoryChangeRepository()
        assert changes.pending(connection, "community", "first")
        batch = preparation.freeze(
            connection, changes, "community", "first", utc_now(), max_count=256, max_chars=20000
        )
        assert batch
        progress = connection.execute("SELECT * FROM memory_relationship_refreshes").fetchone()
        assert progress["request_kind"] == "automatic" and progress["source_version"] == "1:1"
        assert (
            preparation.freeze(
                connection, changes, "community", "first", utc_now(), max_count=256, max_chars=20000
            )
            is None
        )


@pytest.mark.model
@pytest.mark.parametrize(
    "direction,text",
    [
        ("up", "我刚才看你搬书很吃力，帮你把剩下的一箱送到了书架旁。"),
        ("down", "别跟我说话，我才不想听你讲那些无聊的书。"),
        ("neutral", "你好，我叫 Alice，第一次来这里，想看看有些什么书。"),
    ],
)
def test_real_first_description_matches_evidence_and_keeps_scores(tmp_path, direction, text):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={
            "debug_capture_enabled": True,
            "debug_capture_path": str(tmp_path / "captures"),
            "reflection_relationship_attitude_max_chars": 180,
        }
    )
    with TestClient(create_app(settings)) as client:
        create_group(client)
        interaction(client, direction=direction, text=text)
        before = client.get(RELATIONS).json()["items"][0]
        run = request_refresh(client, "alice")[0]["graph_run_id"]
        client.portal.call(finish_relation, client.app.state.application, run)
        after = client.get(RELATIONS).json()["items"][0]
        assert 0 < len(after["attitude_summary"]) <= 180
        assert after["attitude_source_refs"]
        assert after["target_name"] == "alice"
        for key in ("affection", "trust", "attachment", "state_version"):
            assert after[key] == before[key]
        print(
            json.dumps(
                {
                    "direction": direction,
                    "evidence": text,
                    "description": after["attitude_summary"],
                    "run": run,
                },
                ensure_ascii=False,
            )
        )


@pytest.mark.model
def test_real_unreadable_evidence_keeps_limited_description(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={
            "debug_capture_enabled": True,
            "debug_capture_path": str(tmp_path / "captures"),
        }
    )
    with TestClient(create_app(settings)) as client:
        create_group(client)
        interaction(client, text="今晚我会给你送一盆紫色风信子。")
        app = client.app.state.application
        with app.database.transaction() as connection:
            connection.execute(
                "UPDATE conversation_memberships SET joined_after_sequence=999 "
                "WHERE conversation_id='conversation' AND actor_id='first'"
            )
        run = request_refresh(client, "alice")[0]["graph_run_id"]
        client.portal.call(finish_relation, app, run)
        relation = client.get(RELATIONS).json()["items"][0]
        assert relation["attitude_summary"]
        assert "风信子" not in relation["attitude_summary"]
        assert not any(
            word in relation["attitude_summary"] for word in ("记不清", "不记得", "忘了", "失忆")
        )
        assert relation["attitude_source_refs"]
        print(
            json.dumps({"unreadable_description": relation["attitude_summary"]}, ensure_ascii=False)
        )
