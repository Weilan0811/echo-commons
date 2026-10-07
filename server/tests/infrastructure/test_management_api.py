import asyncio
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from historical_messages import historical_receipt
from test_application_lifecycle import settings_for
from test_http_api import create_group

from echo_commons.agents.contracts.recovery import FailureCategory, RecoveryAction
from echo_commons.app.main import create_app
from echo_commons.execution.contracts import Disposition
from echo_commons.execution.recovery import decision
from echo_commons.modules.memory.repositories.thoughts import ThoughtRepository

BASE = "/internal/communities/community"
CONVERSATION = BASE + "/conversations/conversation"
CHARACTER = BASE + "/characters/first"


def post_message(client, identity, text, *, reply=None):
    body = {"player_id": "alice", "client_message_id": identity, "text": text}
    if reply:
        body["reply_to_message_id"] = reply
    response = client.post("/api/conversations/conversation/messages", json=body)
    assert response.status_code == 202, response.text
    return response.json()


def detail(client, url, params=None):
    response = client.get(url, params=params)
    assert response.status_code == 200, response.text
    return response.json()


def seal(client, first, upper, character="first"):
    response = client.post(
        BASE + f"/characters/{character}/conversations/conversation/segments",
        json={"first_sequence": first, "through_sequence": upper},
    )
    assert response.status_code == 200, response.text
    return response.json()


def test_management_discovery_has_explicit_empty_and_missing_scope(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        assert detail(client, "/internal/communities")["items"] == []
        assert detail(client, "/internal/players")["items"] == []
        assert client.get(BASE + "/members").status_code == 404
        create_group(client)
        assert detail(client, BASE)["community_id"] == "community"
        assert len(detail(client, "/internal/players")["items"]) == 2
        assert detail(client, "/internal/players/alice")["display_name"] == "alice"
        assert len(detail(client, BASE + "/members")["items"]) == 4
        assert detail(client, CHARACTER)["character_id"] == "first"
        assert detail(client, CONVERSATION)["next_sequence"] == 1
        assert len(detail(client, CONVERSATION + "/members")["items"]) == 4
        assert detail(client, CHARACTER + "/states")["current"] is not None
        assert detail(client, CHARACTER + "/relationships")["items"] == []
        assert detail(client, CHARACTER + "/relationships/player/alice/evidence")["items"] == []
        assert client.get(CHARACTER + "/relationships/player/missing/evidence").status_code == 404
        for suffix in ("characters/first", "conversations/conversation", "tasks"):
            assert client.get("/internal/communities/other/" + suffix).status_code == 404


def test_management_contract_exposes_typed_speech_and_silence():
    schemas = create_app().openapi()["components"]["schemas"]
    payload = schemas["ConversationResultView"]["properties"]["payload"]
    assert payload["discriminator"]["propertyName"] == "status"
    assert set(payload["discriminator"]["mapping"]) == {"completed", "no_proposal"}
    assert len(payload["oneOf"]) == 2
    speech = schemas["ConversationMessageContent"]
    assert "utterance" in speech["required"]
    assert {"utterance", "thought", "reply_to_message_id"} <= speech["properties"].keys()
    assert schemas["ConversationSilentResult"]["properties"]["output"]["type"] == "null"


def test_management_pages_messages_tasks_and_scoped_traces(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client:
        create_group(client)
        private = historical_receipt(
            client, "private", "第一位的私人材料榆树702", character="first"
        )
        public = post_message(client, "public", "公共材料")
        page = detail(client, CONVERSATION + "/messages", {"limit": 1})
        assert page["has_more"] and page["items"][0]["message_id"] == private["message_id"]
        assert "text" not in page["items"][0]
        second = detail(client, CONVERSATION + "/messages", {"cursor": page["cursor"], "limit": 1})
        assert second["items"][0]["message_id"] == public["message_id"]
        assert not second["has_more"]
        assert client.get(BASE + "/members", params={"cursor": page["cursor"]}).status_code == 400
        assert (
            client.get(CONVERSATION + "/messages", params={"cursor": "invalid"}).status_code == 400
        )
        assert client.get(CONVERSATION + "/messages", params={"limit": 201}).status_code == 422
        private_detail = detail(client, CONVERSATION + "/messages/" + private["message_id"])
        assert {item["actor_id"] for item in private_detail["audience"]} == {"alice", "first"}
        assert private_detail["text"] == "第一位的私人材料榆树702"
        assert client.get(CONVERSATION + "/messages/missing").status_code == 404
        app.state.application.planner.plan()
        tasks = detail(client, BASE + "/tasks", {"character_id": "first"})["items"]
        assert tasks and "snapshot_json" not in tasks[0]
        task_id = tasks[0]["task_id"]
        url = f"/internal/characters/first/tasks/{task_id}"
        inspected = detail(client, url, {"community_id": "community"})
        assert inspected["context"]["scope"]["character_id"] == "first"
        turn = detail(client, CONVERSATION + "/turns/" + tasks[0]["social_turn_id"])
        assert task_id in turn["task_ids"]
        assert private["message_id"] in {
            message_id
            for task in tasks
            for message_id in detail(
                client, CONVERSATION + "/turns/" + task["social_turn_id"]
            )["input_message_ids"]
        }
        assert client.get(BASE + "/tasks", params={"status": "invalid"}).status_code == 422
        assert client.get(BASE + "/tasks", params={"character_id": "missing"}).status_code == 404
        assert (
            client.get(
                url.replace("first", "second"), params={"community_id": "community"}
            ).status_code
            == 404
        )
        trace = "/internal/traces/" + tasks[0]["trace_id"]
        assert detail(client, trace, {"community_id": "community", "character_id": "first"})
        assert client.get(trace, params={"community_id": "other"}).status_code == 404
        assert (
            client.get(
                trace, params={"community_id": "community", "character_id": "second"}
            ).status_code
            == 404
        )
        assert client.get(trace).status_code == 422
        assert detail(
            client, "/internal/traces/" + public["trace_id"], {"community_id": "community"}
        )["traces"]


def test_sealing_is_repeatable_with_real_budget_and_membership_scope(tmp_path):
    config = settings_for(tmp_path, workers=False).model_copy(
        update={"reflection_max_messages_per_segment": 1}
    )
    app = create_app(config)
    with TestClient(app) as client:
        create_group(client)
        historical_receipt(client, "first-private", "第一位私人材料", character="first")
        historical_receipt(client, "second-private", "第二位私人材料", character="second")
        post_message(client, "shared", "公共材料")
        first = seal(client, 1, 3)["segment"]
        assert (first["first_message_sequence"], first["last_message_sequence"]) == (1, 1)
        assert seal(client, 1, 3)["segment"]["segment_id"] == first["segment_id"]
        public = seal(client, 3, 3)["segment"]
        assert public["first_message_sequence"] == 3
        assert seal(client, 1, 3)["segment"]["segment_id"] == first["segment_id"]
        second = seal(client, 2, 3, "second")["segment"]
        assert second["first_message_sequence"] == 2
        url = CHARACTER + "/conversations/conversation/segments"
        assert (
            client.post(url, json={"first_sequence": 1, "through_sequence": 4}).status_code == 400
        )
        assert (
            client.post(url, json={"first_sequence": 3, "through_sequence": 1}).status_code == 422
        )
        with app.state.application.database.read() as connection:
            assert connection.execute("SELECT COUNT(*) FROM memory_segments").fetchone()[0] == 3
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_reflection_management_schedules_and_restarts_real_failed_queue(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client:
        create_group(client)
        post_message(client, "meal", "一起准备晚餐")
        segment = seal(client, 1, 1)["segment"]
        url = CHARACTER + "/reflection/segments"
        response = client.post(url, json={"segment_id": segment["segment_id"]})
        assert response.status_code == 202, response.text
        scheduled = response.json()
        graph = scheduled["graph_run"]["graph_run_id"]
        assert scheduled["source_id"] == segment["segment_id"]
        assert (
            client.post(url, json={"segment_id": segment["segment_id"]}).json()["graph_run"][
                "graph_run_id"
            ]
            == graph
        )
        scope = {"community_id": "community", "character_id": "first"}
        run_url = "/internal/reflection/runs/" + graph
        original = detail(client, run_url, scope)
        assert detail(client, CHARACTER + "/reflection/runs")["items"][0]["graph_run_id"] == graph
        root = next(
            node for node in original["node_tasks"] if node["node_key"] == "segment_summary_plan"
        )
        inspected = detail(client, run_url + "/nodes/" + root["task_id"] + "/input", scope)
        assert inspected["input_ready"]
        assert inspected["input"]["graph_snapshot"] == original["snapshot"]
        assert client.post(run_url + "/restart", params=scope).status_code == 409

        async def fail_required_node():
            application = app.state.application
            lease = await application.reflection_queue.claim("management-test", datetime.now(UTC))
            assert lease.task_id == root["task_id"]
            assert await application.reflection_queue.apply_recovery(
                lease,
                datetime.now(UTC),
                decision("execution_interrupted", FailureCategory.HARNESS, RecoveryAction.FAIL),
            )

        client.portal.call(fail_required_node)
        restarted = client.post(run_url + "/restart", params=scope)
        assert restarted.status_code == 202, restarted.text
        assert restarted.json()["outcome"] == "restarted"
        assert detail(client, run_url, scope)["snapshot"] == original["snapshot"]
        assert client.post(run_url + "/restart", params=scope).status_code == 409
        assert (
            client.post(
                run_url + "/restart", params={**scope, "character_id": "second"}
            ).status_code
            == 404
        )
        empty = client.post(
            CHARACTER + "/reflection/summaries",
            json={
                "conversation_id": "conversation",
                "consumer": "memory_organize",
                "through_sequence": 1,
            },
        )
        assert empty.status_code == 202 and empty.json()["outcome"] == "no_material"
        assert (
            client.post(
                CHARACTER + "/reflection/summaries",
                json={
                    "conversation_id": "conversation",
                    "consumer": "diary_compose",
                    "through_sequence": 1,
                },
            ).status_code
            == 422
        )
        assert client.get(run_url, params={**scope, "community_id": "other"}).status_code == 404
        assert (
            client.get(CHARACTER + "/reflection/runs", params={"status": "bad"}).status_code == 422
        )


def test_memory_management_lists_real_preload_and_scope(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client)
        base = CHARACTER + "/memory/"
        entries = detail(client, base + "entries", {"limit": 1})
        assert entries["items"] and "content" not in entries["items"][0]
        memory_id = entries["items"][0]["memory_id"]
        actual = detail(client, base + "entries/" + memory_id)
        assert actual["content"] and actual["source_kind"]
        other = BASE + "/characters/second/memory/entries/" + memory_id
        assert client.get(other).status_code == 404
        for collection in ("segments", "digests", "entities", "edges"):
            assert detail(client, base + collection)["items"] == []
        assert client.get(base + "entries/missing").status_code == 404
        assert client.get(base + "unknown").status_code == 422
        assert (
            client.get(base + "entries", params={"conversation_id": "conversation"}).status_code
            == 400
        )
        if entries["cursor"]:
            assert (
                client.get(
                    BASE + "/characters/second/memory/entries", params={"cursor": entries["cursor"]}
                ).status_code
                == 400
            )


def test_export_uses_real_ranges_private_perspective_and_source_references(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client:
        create_group(client)
        private = historical_receipt(client, "one", "第一位私有词榆树702", character="first")
        historical_receipt(client, "two", "第二位私有词松树903", character="second")
        public = post_message(client, "three", "公共回复", reply=private["message_id"])
        app.state.application.planner.plan()
        seal(client, 1, 3)
        url = CONVERSATION + "/export"
        body = {"first_sequence": 1, "through_sequence": 3}
        general = client.post(url, json=body)
        assert general.status_code == 200, general.text
        assert "attachment" in general.headers["content-disposition"]
        assert general.json()["counts"]["messages"] == 3
        assert general.json()["thoughts"] == [] and general.json()["memory"] == []
        scoped = client.post(url, json={**body, "character_id": "first"})
        assert scoped.status_code == 200, scoped.text
        exported = scoped.json()
        assert "松树903" not in scoped.text
        assert len(exported["messages"]) == 2 and len(exported["memory"]) == 1
        assert all(task["character_id"] == "first" for task in exported["tasks"])
        narrow = client.post(
            url, json={"first_sequence": 3, "through_sequence": 3, "character_id": "first"}
        )
        assert narrow.status_code == 200, narrow.text
        assert narrow.json()["messages"][0]["message_id"] == public["message_id"]
        assert narrow.json()["memory"] == []
        refs = {item["source_id"] for item in narrow.json()["references"]}
        assert private["message_id"] in refs
        assert "榆树702" not in narrow.text
        assert client.post(url, json={**body, "through_sequence": 4}).status_code == 400
        assert client.post(url, json={**body, "character_id": "missing"}).status_code == 404
        assert client.post(url, json={**body, "credentials": True}).status_code == 422


@pytest.mark.model
def test_management_real_chat_clears_thought_from_diagnostics_and_export(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client:
        create_group(client)
        historical_receipt(
            client, "chat", "小槿，今天我们一起准备晚餐，你想吃什么？", character="first"
        )
        application = app.state.application
        application.planner.plan()

        async def execute():
            lease = await application.queue.claim("management-real-model", datetime.now(UTC))
            outcome = await application.handler.execute(lease)
            assert outcome.disposition is Disposition.COMPLETED

        client.portal.call(execute)
        with application.database.read() as connection:
            replies = connection.execute(
                "SELECT message_id, visibility FROM messages WHERE source_turn_id IS NOT NULL"
            ).fetchall()
            for message in replies:
                assert message["visibility"] == "recipients"
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM message_recipients WHERE message_id = ?",
                        (message["message_id"],),
                    ).fetchone()[0]
                    == 2
                )
            thought = connection.execute(
                "SELECT * FROM thoughts WHERE character_id = 'first'"
            ).fetchone()
            upper = connection.execute("SELECT MAX(sequence) FROM messages").fetchone()[0]
        # 合法沉默仍检查真实结果；有内心记录时验证全部读取路径的清除行为。
        if thought is not None:
            task_id = detail(client, BASE + "/tasks", {"character_id": "first"})["items"][0][
                "task_id"
            ]
            result_url = f"/internal/characters/first/tasks/{task_id}"
            results = detail(client, result_url, {"community_id": "community"})["results"]
            result = next(item for item in results if item["result_id"] == thought["result_id"])
            assert result["payload"]["status"] == "completed"
            assert result["payload"]["output"]["payload"]["thought"] == thought["content"]
            historical_receipt(client, "next", "继续聊聊晚餐的安排。", character="first")
            application.planner.plan()
            tasks = detail(client, BASE + "/tasks", {"character_id": "first"})["items"]
            task = tasks[-1]
            url = f"/internal/characters/first/tasks/{task['task_id']}/context"
            original = detail(client, url, {"community_id": "community"})
            assert original["memory"]["history_thoughts"]
            with application.database.read() as connection:
                saved_snapshot = application.handler.execution.tasks.snapshot(
                    connection,
                    task["task_id"],
                ).model_dump_json()
            segment = seal(client, 1, upper)["segment"]
            scheduled = client.post(
                CHARACTER + "/reflection/segments", json={"segment_id": segment["segment_id"]}
            ).json()
            graph = scheduled["graph_run"]["graph_run_id"]
            with application.database.transaction() as connection:
                assert ThoughtRepository().clear_text(
                    connection,
                    "community",
                    "first",
                    thought["thought_id"],
                    datetime.now(UTC),
                )
            results = detail(client, result_url, {"community_id": "community"})["results"]
            result = next(item for item in results if item["result_id"] == thought["result_id"])
            assert result["thought_removed_at_utc"]
            assert result["payload"]["output"]["payload"]["thought"] is None
            filtered = detail(client, url, {"community_id": "community"})
            item = next(
                item
                for item in filtered["memory"]["history_thoughts"]
                if item["thought_id"] == thought["thought_id"]
            )
            assert item["content"] is None and item["content_removed_at_utc"]
            run_url = "/internal/reflection/runs/" + graph
            scope = {"community_id": "community", "character_id": "first"}
            run = detail(client, run_url, scope)
            assert all(
                item["content"] is None
                for item in run["snapshot"]["materials"]
                if item["kind"] == "thought"
            )
            root = next(
                node for node in run["node_tasks"] if node["node_key"] == "segment_summary_plan"
            )
            node = detail(client, run_url + "/nodes/" + root["task_id"] + "/input", scope)
            assert node["input_ready"]
            assert all(
                item["content"] is None
                for item in node["input"]["graph_snapshot"]["materials"]
                if item["kind"] == "thought"
            )
            with application.database.read() as connection:
                snapshot = application.handler.execution.tasks.snapshot(connection, task["task_id"])
                assert snapshot.model_dump_json() == saved_snapshot
        response = client.post(
            CONVERSATION + "/export",
            json={
                "first_sequence": 1,
                "through_sequence": upper,
                "character_id": "first",
            },
        )
        assert response.status_code == 200, response.text
        if thought is not None:
            assert response.json()["thoughts"][0]["content"] is None
            assert thought["content"] not in response.text


@pytest.mark.model
def test_management_http_runs_three_real_reflections_and_exports_memory(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client:
        create_group(client)
        historical_receipt(
            client, "personal", "我的晚餐暗号是榆树702，我最喜欢番茄炒蛋。", character="first"
        )
        historical_receipt(client, "excluded", "第二位的私人暗号松树903。", character="second")
        post_message(client, "event", "今晚我们约好一起做饭，我会提前买好番茄和鸡蛋。")
        segment = seal(client, 1, 3)["segment"]
        application = app.state.application

        async def finish_graph(graph_id):
            async with asyncio.timeout(300):
                while True:
                    await application.supervisor.workers["reflection-0"].run_once()
                    with application.database.read() as connection:
                        row = connection.execute(
                            "SELECT status FROM reflection_graph_runs WHERE graph_run_id = ?",
                            (graph_id,),
                        ).fetchone()
                    if row[0] in {"completed", "partial", "failed", "cancelled"}:
                        assert row[0] in {"completed", "partial"}
                        return
                    await asyncio.sleep(0.05)

        scope = {"community_id": "community", "character_id": "first"}
        response = client.post(
            CHARACTER + "/reflection/segments", json={"segment_id": segment["segment_id"]}
        )
        assert response.status_code == 202, response.text
        graph = response.json()["graph_run"]["graph_run_id"]
        client.portal.call(finish_graph, graph)
        actual = detail(client, "/internal/reflection/runs/" + graph, scope)
        assert actual["result"]["status"] == "approved"
        assert actual["artifacts"] and actual["facts"]
        for node in actual["node_tasks"]:
            inspected = detail(
                client, f"/internal/reflection/runs/{graph}/nodes/{node['task_id']}/input", scope
            )
            if node["status"] == "completed":
                assert inspected["input_ready"]
        saved = detail(client, CHARACTER + "/memory/segments/" + segment["segment_id"])
        assert saved["status"] == "ingested" and saved["summary_text"]
        assert saved["coverage"]
        for consumer in ("continuity_compress", "memory_organize"):
            body = {"conversation_id": "conversation", "consumer": consumer, "through_sequence": 3}
            response = client.post(CHARACTER + "/reflection/summaries", json=body)
            assert response.status_code == 202, response.text
            scheduled = response.json()
            assert scheduled["outcome"] == "scheduled"
            repeated = client.post(CHARACTER + "/reflection/summaries", json=body)
            assert (
                repeated.json()["graph_run"]["graph_run_id"]
                == scheduled["graph_run"]["graph_run_id"]
            )
            client.portal.call(finish_graph, scheduled["graph_run"]["graph_run_id"])
            result = detail(
                client, "/internal/reflection/runs/" + scheduled["graph_run"]["graph_run_id"], scope
            )
            assert result["result"]["status"] == "approved"
            assert "松树903" not in str(result)
        for collection, key in (
            ("digests", "digest_id"),
            ("entries", "memory_id"),
            ("entities", "entity_id"),
            ("edges", "edge_id"),
        ):
            records = detail(client, CHARACTER + "/memory/" + collection)["items"]
            for record in records:
                actual = detail(client, CHARACTER + f"/memory/{collection}/" + record[key])
                assert actual[key] == record[key]
        saved = detail(client, CHARACTER + "/memory/segments/" + segment["segment_id"])
        assert saved["consumption"]
        response = client.post(
            CONVERSATION + "/export",
            json={
                "first_sequence": 1,
                "through_sequence": 3,
                "character_id": "first",
            },
        )
        assert response.status_code == 200, response.text
        assert "松树903" not in response.text
        assert {item["record_kind"] for item in response.json()["memory"]} >= {
            "segments",
            "digests",
        }
        assert (
            client.post(
                CHARACTER + "/reflection/summaries",
                json={
                    "conversation_id": "conversation",
                    "consumer": "memory_organize",
                    "through_sequence": 3,
                },
            ).json()["outcome"]
            == "no_material"
        )
        with application.database.read() as connection:
            assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
