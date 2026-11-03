import json
from datetime import UTC, datetime
from importlib.resources import files
from pathlib import Path

import pytest
from fastapi.testclient import TestClient
from support.activities import activity_game, message, prepare
from support.activity_actions import ALICE, CHARACTER, create_character_black, play_in, task_row
from support.application import settings_for
from support.authoring import confirm, create_draft
from support.games import create, move, operation
from support.http import create_group

from echo_commons.agents.contracts.activity import IntentProposal
from echo_commons.agents.contracts.errors import ExecutionError
from echo_commons.app.composition import assemble
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.infrastructure.database.connection import Database
from echo_commons.infrastructure.database.errors import StorageError
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.activities.gameplay.contracts import AnalysisRequest
from echo_commons.modules.conversations.domain.message import PlayerMessage


def decision_settings(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    registry = Path(settings.model_registry_path)
    target = tmp_path / "models.toml"
    target.write_text(
        registry.read_text(encoding="utf-8").replace(
            "[decision]\nenabled = false", "[decision]\nenabled = true"
        ),
        encoding="utf-8",
    )
    return settings.model_copy(update={"model_registry_path": str(target)})


@pytest.mark.model
def test_real_local_decision_submits_actual_selected_action(tmp_path, record_testsuite_property):
    with TestClient(create_app(decision_settings(tmp_path))) as client:
        game = activity_game(client)
        message(client, game, "嘿嘿，输了的人负责讲个笑话怎么样？")
        app = client.app.state.application
        (identity,) = app.activity_coordinator.scan()
        assert task_row(app, identity)["mode"] == "decision"
        lease = client.portal.call(app.activity_queue.claim, "local-model", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        assert artifact["mode"] in ("decision", "decision_then_ordinary")
        assert artifact["decision_response"]["answers"]["action"]["choice"]
        result = app.activity_commit.commit(lease, artifact)
        action = artifact["run"]["output"]["payload"]["action"]
        assert result["receipt"]["result"]["x"] == action["x"]
        assert result["receipt"]["result"]["y"] == action["y"]
        assert app.activity_commit.commit(lease, artifact) == result
        if artifact["mode"] == "decision":
            with app.database.read() as connection:
                assert connection.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0] == 0
        record_testsuite_property("local_artifact", json.dumps(artifact, ensure_ascii=False))


@pytest.mark.model
def test_real_local_new_intent_uses_ordinary_understanding(tmp_path, record_testsuite_property):
    with TestClient(create_app(decision_settings(tmp_path))) as client:
        game = activity_game(client)
        message(
            client,
            game,
            "我想跟你约定这盘先练习封堵，每次我忘记看对手的威胁你就提醒我，"
            "不过你可以有自己的想法，想换个练法也说说？",
        )
        app = client.app.state.application
        app.activity_coordinator.scan()
        lease = client.portal.call(app.activity_queue.claim, "new-intent", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        record_testsuite_property("delegation", json.dumps(artifact, ensure_ascii=False))
        assert artifact["mode"] == "decision_then_ordinary"
        assert artifact["decision_response"]["answers"]["intent_update"]["choice"] == "understand"
        assert artifact["run"]["steps"][0]["response_kind"] == "decision"
        assert artifact["run"]["usage_summary"]["model_request_count"] >= 2
        assert client.portal.call(app.activity_execution.execute, lease) == artifact
        with app.database.read() as connection:
            calls = connection.execute(
                "SELECT payload_json FROM task_execution_events "
                "WHERE task_id=? AND event_kind='run_finished'",
                (lease.task_id,),
            ).fetchall()
            assert len(calls) == 2
            assert (
                sum(
                    json.loads(row[0])["observation"]["usage_summary"]["model_request_count"]
                    for row in calls
                )
                == artifact["run"]["usage_summary"]["model_request_count"]
            )
        assert app.activity_commit.commit(lease, artifact)


@pytest.mark.model
def test_real_ordinary_action_saves_full_result_and_private_thought(
    tmp_path, record_testsuite_property
):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={"debug_capture_enabled": True, "debug_capture_path": str(tmp_path / "captures")}
    )
    with TestClient(create_app(settings)) as client:
        game = activity_game(client)
        original = message(client, game, "哟，这么厉害？再赢我我可要哭啦，哈哈。")
        app = client.app.state.application
        (identity,) = app.activity_coordinator.scan()
        lease = client.portal.call(app.activity_queue.claim, "real-model", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        assert artifact["mode"] == "ordinary"
        assert artifact["run"]["usage_summary"]["total_tokens"] > 0
        assert (
            artifact["run"]["output"]["payload"]["understanding"]["messages"][0]["message_id"]
            == original.message_id
        )
        app.communities.update(
            "community", expected_version=1, world_time=datetime(2041, 1, 2, tzinfo=UTC)
        )
        receipt = app.activity_commit.commit(lease, artifact)
        assert app.activity_commit.commit(lease, artifact) == receipt
        assert task_row(app, identity)["status"] == "completed"
        with app.database.read() as connection:
            thoughts = connection.execute(
                "SELECT * FROM thoughts WHERE activity_result_id=?", (receipt["result_id"],)
            ).fetchall()
            assert len(thoughts) == 1 and thoughts[0]["result_id"] is None
            assert thoughts[0]["game_day"] == "2041-01-02"
            assert (
                thoughts[0]["content"]
                == artifact["run"]["output"]["payload"]["understanding"]["thought"]
            )
            assert connection.execute("SELECT COUNT(*) FROM activity_results").fetchone()[0] == 1
        assert not app.activity_context.pending_sources("community", "first", game)["message_ids"]
        record_testsuite_property("artifact", json.dumps(artifact, ensure_ascii=False))
        record_testsuite_property("receipt", json.dumps(receipt, ensure_ascii=False))


@pytest.mark.model
@pytest.mark.parametrize("local", [False, True], ids=["ordinary", "local"])
def test_real_complete_match_with_rapfi_opponent(tmp_path, local, record_testsuite_property):
    settings = decision_settings(tmp_path) if local else settings_for(tmp_path, workers=False)
    settings = settings.model_copy(update={"retry_backoff_seconds": 0})
    with TestClient(create_app(settings)) as client:
        create_group(client, memory_mode="simple")
        app = client.app.state.application
        game = create_character_black(app)
        message(client, game, "来一盘吧，输赢都没关系，看看我们能下出什么花样。")
        moves = []
        for index in range(225):
            with app.database.read() as connection:
                context = app.game_queries.participant_context(
                    connection, "community", CHARACTER, game
                )
                view = app.games.read_view(connection, context.access)
                if view.status != "running":
                    break
                if not view.opportunities:
                    context = app.game_queries.participant_context(
                        connection, "community", ALICE, game
                    )
                    view = app.games.read_view(connection, context.access)
            if context.access.seat_id == "black":
                (task_id,) = app.activity_coordinator.scan()
                for _ in range(settings.max_agent_attempts):
                    client.portal.call(app.supervisor.workers["activities-0"].run_once)
                    row = task_row(app, task_id)
                    if row["status"] in ("completed", "failed", "cancelled"):
                        break
                assert row["status"] == "completed", row
                with app.database.read() as connection:
                    result = app.activity_commit.results.for_task(connection, task_id)
                    receipt = json.loads(result["receipt_json"])
                    artifact = json.loads(result["artifact_json"])
                    assert (
                        receipt["result"]["x"]
                        == artifact["run"]["output"]["payload"]["action"]["x"]
                    )
                    moves.append({"seat": "black", "mode": artifact["mode"], "receipt": receipt})
            else:
                analysis = client.portal.call(
                    app.game_analysis.analyze,
                    AnalysisRequest(view=view, opportunity=view.opportunities[0]),
                )
                candidate = next(
                    c
                    for c in analysis.candidates
                    if c.candidate_id == analysis.recommended_candidate_id
                )
                with app.database.transaction() as connection:
                    receipt = play_in(app, connection, game, ALICE, candidate.action)
                moves.append({"seat": "white", "receipt": receipt.model_dump(mode="json")})
            print(f"{local=}, move={index + 1}, seat={moves[-1]['seat']}", flush=True)
        with app.database.read() as connection:
            game_state = app.game_queries.participant_context(
                connection, "community", CHARACTER, game
            ).game
            assert game_state.status == "finished"
            assert (
                connection.execute("SELECT COUNT(*) FROM activity_working_memory").fetchone()[0]
                == 0
            )
        record_testsuite_property(
            f"complete_match_{local}",
            json.dumps(
                {"game": game_state.model_dump(mode="json"), "moves": moves}, ensure_ascii=False
            ),
        )


@pytest.mark.model
def test_real_write_rollback_and_restart_reuse_saved_generation(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(update={"retry_backoff_seconds": 0})
    with TestClient(create_app(settings)) as client:
        game = activity_game(client)
        original = message(client, game, "能不能陪我练练？别笑我水平差哦。")
        app = client.app.state.application
        (identity,) = app.activity_coordinator.scan()
        lease = client.portal.call(app.activity_queue.claim, "before-restart", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        row = task_row(app, identity)
        snapshot = app.activity_context.restore("community", "first", row["input_id"])
        proposal = app.activity_execution.outputs.restore_result(
            json.dumps(artifact["run"])
        ).output.payload
        occupied = snapshot.material.game.view.state.stones[0]
        illegal = proposal.model_copy(
            update={"action": proposal.action.model_copy(update={"x": occupied.x, "y": occupied.y})}
        )
        with pytest.raises(ExecutionError, match="activity_action_illegal"):
            app.activity_execution.review.proposal(row, illegal, snapshot)
        with app.database.transaction() as connection:
            connection.execute(
                "CREATE TRIGGER reject_activity_result BEFORE INSERT ON activity_results "
                "BEGIN SELECT RAISE(ABORT,'verification write failure'); END"
            )
        with pytest.raises(StorageError):
            app.activity_commit.commit(lease, artifact)
        with app.database.read() as connection:
            current = app.game_queries.participant_context(connection, "community", CHARACTER, game)
            assert current.game.state_version == row["state_version"]
            assert connection.execute("SELECT COUNT(*) FROM activity_results").fetchone()[0] == 0
            assert connection.execute("SELECT COUNT(*) FROM thoughts").fetchone()[0] == 0
            assert (
                connection.execute("SELECT COUNT(*) FROM activity_working_memory").fetchone()[0]
                == 0
            )
            assert (
                connection.execute("SELECT COUNT(*) FROM activity_observation_progress").fetchone()[
                    0
                ]
                == 0
            )
        assert (
            original.message_id
            in app.activity_context.pending_sources("community", "first", game)["message_ids"]
        )
        with app.database.transaction() as connection:
            connection.execute("DROP TRIGGER reject_activity_result")
        blocker = app.database.connect()
        try:
            blocker.execute("BEGIN IMMEDIATE")
            with pytest.raises(StorageError) as failure:
                app.activity_commit.commit(lease, artifact)
            assert failure.value.retryable
        finally:
            blocker.rollback()
            blocker.close()
        client.portal.call(
            app.activity_queue.apply_recovery,
            lease,
            utc_now(),
            app.activity_queue.recovery.classify(failure.value),
        )
        later = message(client, game, "刚才那句还没说完，我想试试自己想办法。")
    with TestClient(create_app(settings)) as client:
        app = client.app.state.application
        newer = client.portal.call(app.activity_queue.claim, "after-restart", utc_now())
        assert newer.task_id == identity and newer.generation > lease.generation
        restored = client.portal.call(app.activity_execution.execute, newer)
        assert restored == artifact
        result = app.activity_commit.commit(newer, restored)
        assert app.activity_commit.commit(newer, restored) == result
        assert task_row(app, identity)["request_id"] == row["request_id"]
        assert app.activity_context.pending_sources("community", "first", game)["message_ids"] == (
            later.message_id,
        )
        app.communities.update("community", expected_version=1, status="paused")
        response = client.post(
            "/internal/maintenance/cleanup", json={"community_ids": ["community"], "dry_run": False}
        )
        assert response.status_code == 200, response.text
        with app.database.read() as connection:
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
            for table in ("activity_tasks", "activity_results", "thoughts"):
                assert connection.execute(f"SELECT COUNT(*) FROM {table}").fetchone()[0] == 0


@pytest.mark.model
@pytest.mark.parametrize("local", [False, True], ids=["ordinary", "local"])
@pytest.mark.parametrize(
    "situation,text,intent",
    [
        ("suggestion", "我觉得你可以下在边线，比如零、零那里，你觉得呢？", None),
        ("challenge", "这可是正式比赛哦，拿出你的真本事，别被我赢了还找借口，哈哈。", None),
        (
            "promise",
            "你刚才答应陪我练练的嘛，怎么一下就这么厉害了，呜呜。",
            "陪 alice 练习，关注她能否理解每步的后果",
        ),
    ],
)
def test_real_same_board_context_variants(
    tmp_path, local, situation, text, intent, record_testsuite_property
):
    settings = decision_settings(tmp_path) if local else settings_for(tmp_path, workers=False)
    with TestClient(create_app(settings)) as client:
        game = activity_game(client)
        source = message(client, game, text)
        app = client.app.state.application
        if intent:
            snapshot = prepare(client, game)
            app.activity_working_memory.replace(
                "community",
                "first",
                snapshot.snapshot_id,
                expected_version=0,
                intents=(IntentProposal(content=intent, message_ids=(source.message_id,)),),
            )
        (identity,) = app.activity_coordinator.scan()
        lease = client.portal.call(app.activity_queue.claim, "context-variation", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        result = app.activity_commit.commit(lease, artifact)
        assert result and task_row(app, identity)["status"] == "completed"
        record_testsuite_property(
            f"variant_{situation}_{local}",
            json.dumps(
                {
                    "message": text,
                    "prior_intent": intent,
                    "artifact": artifact,
                    "receipt": result,
                },
                ensure_ascii=False,
            ),
        )


@pytest.mark.model
@pytest.mark.parametrize("local", [False, True], ids=["ordinary", "local"])
def test_real_same_board_with_distinct_character(tmp_path, local, record_testsuite_property):
    settings = decision_settings(tmp_path) if local else settings_for(tmp_path, workers=False)
    profile = "我是周谨，在棋社练棋。对局时重视棋形与承诺，听到挑衅会认真考虑，"
    profile += "对方撒娇也不会马上答应让棋，会先弄清她想练习什么。"
    with TestClient(create_app(settings)) as client:
        create_group(client, memory_mode="simple")
        draft, _ = create_draft(
            client,
            name="周谨",
            profile=profile,
            voice="话语简短平和，理由说清楚。",
            relational_dynamics="尊重对方，也保留自己的判断，愿意协商约定。",
        )
        blueprint, _ = confirm(client, draft)
        response = client.post(
            "/api/communities/community/characters",
            json={
                "player_id": "alice",
                "blueprint_id": blueprint["blueprint_id"],
                "character_id": "competitor",
                "memory_mode": "simple",
            },
        )
        assert response.status_code == 201, response.text
        created, _ = create(client)
        game = created["game_id"]
        operation(
            client,
            game,
            "participants",
            seat_id="white",
            participant={"kind": "character", "character_id": "competitor"},
        )
        operation(client, game, "start")
        move(client, game, "alice", 7, 7)
        message(client, game, "哟，这么厉害？再赢我我可要哭啦，哈哈。")
        app = client.app.state.application
        app.activity_coordinator.scan()
        lease = client.portal.call(app.activity_queue.claim, "distinct-character", utc_now())
        artifact = client.portal.call(app.activity_execution.execute, lease)
        assert artifact["run"]["agent_id"] == "character:community:competitor"
        assert app.activity_commit.commit(lease, artifact)
        record_testsuite_property(
            f"persona_{local}",
            json.dumps(
                {
                    "profile": profile,
                    "artifact": artifact,
                },
                ensure_ascii=False,
            ),
        )


@pytest.mark.model
@pytest.mark.asyncio
async def test_migration_preserves_real_conversation_thought(tmp_path):
    settings = settings_for(tmp_path, workers=False)
    database = Database(settings.database_path)
    scripts = tmp_path / "version30"
    scripts.mkdir()
    for source in files("echo_commons.infrastructure.database.sql").iterdir():
        if source.name.endswith(".sql") and int(source.name[:4]) <= 30:
            (scripts / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    assert initialize(database, sql_directory=scripts) == 30
    app = assemble(settings)
    try:
        app.communities.register_player("alice", player_id="alice")
        app.communities.create("迁移验证", "UTC", community_id="community", player_id="alice")
        app.communities.update("community", expected_version=0, status="active")
        app.characters.create(
            "community", "xiaojin", character_id="first", player_id="alice", memory_mode="simple"
        )
        app.conversations.create(
            "community",
            "direct",
            (ALICE, CHARACTER),
            conversation_id="conversation",
            player_id="alice",
        )
        app.intake.send(
            "community",
            "conversation",
            PlayerMessage(
                "alice",
                "migration-chat",
                "小槿，今天想画什么？我想听听你的想法。",
            ),
        )
        app.planner.plan()
        lease = await app.queue.claim("historical-conversation", utc_now())
        assert lease is not None
        prepared = app.handler.execution.prepare(lease.task_id, attempt=lease.attempt)
        invocation = prepared.invocation.model_copy(
            update={
                "execution_policy": prepared.invocation.execution_policy.model_copy(
                    update={
                        "output_instructions": "本次验证私人内心保存：请按照本次输出契约返回 JSON，"
                        "在 thought 中记录自己此刻的简短念头，"
                        "在 utterance 中回应眼前问题。",
                    }
                ),
            }
        )
        result = await prepared.agent.run(invocation)
        assert result.status == "completed", result.model_dump(mode="json")
        assert app.handler.commit.commit(lease, invocation, result).message_id
        with database.read() as connection:
            before = [dict(row) for row in connection.execute("SELECT * FROM thoughts")]
            assert before and before[0]["content"]
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM conversation_results WHERE status='approved'"
                ).fetchone()[0]
                == 1
            )
        assert initialize(database) == initialize(database) == 33
        with database.read() as connection:
            after = [dict(row) for row in connection.execute("SELECT * FROM thoughts")]
            assert all(row.pop("activity_result_id") is None for row in after)
            assert after == before
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    finally:
        await app.rapfi.close()
        await app.gateway.close()
        await app.image_generations.gateway.close()
        if app.decisions:
            await app.decisions.close()
        if app.embeddings:
            await app.embeddings.close()
