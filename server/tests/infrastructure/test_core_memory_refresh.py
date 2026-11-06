import asyncio
import json
import time
from uuid import uuid4
from xml.etree.ElementTree import fromstring

import pytest
from fastapi.testclient import TestClient
from support.application import settings_for
from support.records import create_memory_group

from echo_commons.agents.contracts.output import OutputRegistry
from echo_commons.agents.harness.prompt import read_prompt_resource
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.modules.memory.domain.views import ViewReadingScope
from echo_commons.modules.memory.repositories.changes import MemoryChangeRepository
from echo_commons.modules.memory.services.view_materials import (
    ViewInputBudgetExceeded,
    ViewMaterialPreparation,
)
from echo_commons.modules.reflection.contracts.candidates import ViewModelAction
from echo_commons.modules.reflection.contracts.context import VIEW_NODE_CONTRACT
from echo_commons.modules.reflection.domain.graph import ReflectionNodeKind
from echo_commons.modules.reflection.tasks.input import prepare_node_input
from echo_commons.modules.reflection.tasks.projection import NodeReferences
from echo_commons.modules.reflection.tasks.prompt import project_node
from echo_commons.shared.errors import ConflictError

URL = "/internal/communities/community/characters/first/reflection/core-memory"


def test_core_projection_keeps_reading_bookkeeping_out_of_model_facts(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_memory_group(client)
        response = client.post(URL, json={"request_id": str(uuid4())})
        graph_id = response.json()["graph_run"]["graph_run_id"]
        app = client.app.state.application
        with app.database.read() as connection:
            snapshot = app.reflection.runs.snapshot(connection, "community", "first", graph_id)
        node = prepare_node_input(
            snapshot,
            graph_run_id=graph_id,
            node_task_id="projection",
            node_key="core_memory_view",
            node_kind=ReflectionNodeKind.CORE_MEMORY_VIEW,
        )
        outputs = OutputRegistry()
        outputs.register(VIEW_NODE_CONTRACT, ViewModelAction)
        prompt = project_node(node, output_contract=VIEW_NODE_CONTRACT, outputs=outputs)
        text = "\n".join(message.content for message in prompt.messages)
        instructions = fromstring(prompt.messages[0].content)
        assert instructions.tag == "reflection_instructions"
        assert instructions.text.strip() == read_prompt_resource("reflection/common.md")
        assert "<character_voice>" in text
        assert "<reading_scope>" in text
        assert '"provided_record_count": 4' in text
        assert "processed_versions" not in text and "eligible_versions" not in text
        assert "core_memory_request" not in text
        assert text.index("本节点的输出 JSON Schema") < text.index("<整理示例>")
        output = fromstring(prompt.messages[2].content)
        assert output.tag == "output_contract"
        schema = json.loads(output.text.strip().split("\n", 1)[1])
        assert schema["properties"]["content"]["maxLength"] == 600
        assert text.index("<整理示例>") < text.index("<character_profile>")
        assert text.index("本次材料与只读背景") < text.index("<reading_scope>")
        assert text.index("<reading_scope>") < text.index("本节点允许引用的来源标签")
        labels = NodeReferences.from_input(node)
        with pytest.raises(ValueError, match="Unknown view material number"):
            labels.bind(ViewModelAction(content="不能使用不存在的来源。", sources=[999999]))
        second = client.post(URL.replace("/first/", "/second/"), json={"request_id": str(uuid4())})
        second_id = second.json()["graph_run"]["graph_run_id"]
        with app.database.read() as connection:
            other = app.reflection.runs.snapshot(connection, "community", "second", second_id)
        other_node = prepare_node_input(
            other,
            graph_run_id=second_id,
            node_task_id="other-projection",
            node_key="core_memory_view",
            node_kind=ReflectionNodeKind.CORE_MEMORY_VIEW,
        )
        other_prompt = project_node(other_node, output_contract=VIEW_NODE_CONTRACT, outputs=outputs)
        assert prompt.messages[:5] == other_prompt.messages[:5]
        no_examples = project_node(
            node,
            output_contract=VIEW_NODE_CONTRACT,
            outputs=outputs,
            examples={"core_memory_view": ""},
        )
        assert all("<整理示例>" not in item.content for item in no_examples.messages)


def test_core_refresh_freezes_real_records_and_reuses_request(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_memory_group(client)
        request_id = str(uuid4())
        response = client.post(URL, json={"request_id": request_id})
        assert response.status_code == 202, response.text
        repeated = client.post(URL, json={"request_id": request_id})
        assert repeated.json()["graph_run"] == response.json()["graph_run"]
        status = client.get(URL).json()
        assert status["max_chars"] == 600
        progress = status["refresh"]
        assert progress["selected_memory_ids"]
        assert not progress["unread_memory_ids"]
        assert progress["processed_count"] == progress["total_count"]
        app = client.app.state.application
        with app.database.read() as connection:
            batch = MemoryChangeRepository().get(connection, "community", "first", request_id)
            materials = json.loads(batch["materials_json"])
            records = [item for item in materials if item["fact_kind"] == "memory_fact"]
            assert len(records) == progress["total_count"]
            for record in records:
                content = json.loads(record["content"])
                assert "supporting_materials" not in content
                sources = app.reflection_graph_commit.facts.organization.provenance.record_sources(
                    connection,
                    "community",
                    "first",
                    "fact",
                    record["source_id"],
                    int(record["version"]),
                )
                assert sources and all(item["readable"] for item in sources)
                assert content["support_readable"]
            other = "/internal/communities/community/characters/second/reflection/core-memory"
        assert client.post(other, json={"request_id": request_id}).status_code == 409


def test_core_budget_keeps_unread_records_and_rejects_no_progress(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_memory_group(client)
        with client.app.state.application.database.read() as connection:
            repository = ViewMaterialPreparation()
            selected = repository.select(
                connection,
                "community",
                "first",
                utc_now(),
                set(),
                max_count=3,
                max_chars=20000,
                batch_id=str(uuid4()),
                version="1",
                fresh=True,
            )
            request = ViewReadingScope.from_materials(selected)
            assert len(request.selected_memory_ids) == 2
            assert len(request.unread_memory_ids) == 2
            assert not request.complete
            assert set(request.eligible_versions) == set(
                request.selected_memory_ids + request.unread_memory_ids
            )
            exact_budget = sum(len(item["content"]) for item in selected)
            limited = repository.select(
                connection,
                "community",
                "first",
                utc_now(),
                set(),
                max_count=3,
                max_chars=exact_budget,
                batch_id=str(uuid4()),
                version="1",
                fresh=True,
            )
            assert (
                ViewReadingScope.from_materials(limited).selected_memory_ids
                == request.selected_memory_ids
            )
            assert sum(len(item["content"]) for item in limited) <= exact_budget
            with pytest.raises(ViewInputBudgetExceeded):
                repository.select(
                    connection,
                    "community",
                    "first",
                    utc_now(),
                    set(),
                    max_count=1,
                    max_chars=20000,
                    batch_id=str(uuid4()),
                    version="1",
                )


def test_core_frozen_scope_rejects_removed_record(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_memory_group(client)
        response = client.post(URL, json={"request_id": str(uuid4())})
        graph_id = response.json()["graph_run"]["graph_run_id"]
        app = client.app.state.application
        with app.database.transaction() as connection:
            snapshot = app.reflection.runs.snapshot(connection, "community", "first", graph_id)
            repository = MemoryChangeRepository()
            repository.check(connection, snapshot)
            identity = ViewReadingScope.from_materials(
                [item.model_dump(mode="json") for item in snapshot.materials]
            ).selected_memory_ids[0]
            connection.execute(
                "UPDATE memory_facts SET status='invalid' WHERE memory_id=?",
                (identity,),
            )
            with pytest.raises(ConflictError):
                repository.check(connection, snapshot)


def test_core_refresh_requires_full_memory_mode(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_memory_group(client, memory_mode="simple")
        assert client.post(URL, json={"request_id": str(uuid4())}).status_code == 409


async def finish_graph(application, graph_id):
    dispatcher = application.supervisor.workers["reflection-0"].dispatcher
    deadline = time.monotonic() + 180
    while time.monotonic() < deadline:
        with application.database.read() as connection:
            run = application.reflection.runs.get(connection, "community", "first", graph_id)
        if run.is_terminal:
            assert run.status == "completed", run
            return
        lease = await application.reflection_queue.claim(dispatcher.owner, utc_now())
        if lease is None:
            await asyncio.sleep(1)
        else:
            await dispatcher._execute(lease)
    raise TimeoutError("Core refresh did not finish")


@pytest.mark.model
def test_real_core_budget_and_full_no_op_clear_only_view(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={
            "reflection_core_memory_max_chars": 300,
            "debug_capture_enabled": True,
            "debug_capture_path": str(tmp_path / "captures"),
        }
    )
    with TestClient(create_app(settings)) as client:
        create_memory_group(client)
        app = client.app.state.application
        response = client.post(URL, json={"request_id": str(uuid4())})
        client.portal.call(finish_graph, app, response.json()["graph_run"]["graph_run_id"])
        before = client.get(URL).json()
        assert 0 < len(before["content"]) <= 300
        assert before["source_refs"]
        with app.database.transaction() as connection:
            connection.execute(
                "UPDATE memory_facts SET status='invalid' WHERE character_id='first'",
            )
            page_count = connection.execute(
                "SELECT COUNT(*) FROM memory_facts WHERE character_id='first'"
            ).fetchone()[0]
        response = client.post(URL, json={"request_id": str(uuid4())})
        client.portal.call(finish_graph, app, response.json()["graph_run"]["graph_run_id"])
        after = client.get(URL).json()
        assert after["content"] == ""
        assert after["refresh"]["outcome"] == "no_op"
        assert after["refresh"]["total_count"] == 0
        with app.database.read() as connection:
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM memory_facts WHERE character_id='first'"
                ).fetchone()[0]
                == page_count
            )
