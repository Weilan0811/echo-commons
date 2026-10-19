import asyncio
import json
from datetime import UTC, datetime, timedelta
from importlib.resources import files

import pytest
from fastapi.testclient import TestClient
from support.application import settings_for
from support.games import create as create_game
from support.games import operation
from support.http import create_group
from support.migrations import load_history
from support.social import build_planning_system, send

from echo_commons.agents.contracts.output import (
    CHARACTER_MESSAGE_CONTRACT,
    CharacterMessageProposal,
    OutputRegistry,
)
from echo_commons.agents.contracts.run import AgentRunStatus
from echo_commons.app.composition import assemble
from echo_commons.app.main import create_app
from echo_commons.execution.contracts import Disposition
from echo_commons.infrastructure.database.migrations import initialize
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.conversations.export import ConversationExport
from echo_commons.modules.conversations.tasks.prompt import project_snapshot
from echo_commons.modules.social.continuation import ContinuationPolicy
from echo_commons.shared.actors import ActorRef
from echo_commons.shared.errors import ConflictError, ConversationArchived, IdempotencyConflict


@pytest.fixture
def initiation_system(tmp_path):
    system = build_planning_system(tmp_path)
    application = assemble(
        settings_for(tmp_path, workers=False).model_copy(
            update={"database_path": str(system.database.path)}
        )
    )
    yield application, system
    asyncio.run(application.gateway.close())


def request(application, situation="你看到窗边的猫把画笔碰倒了，想和在场的人分享。", **changes):
    return application.conversation_initiations.request(
        "community",
        "conversation",
        changes.pop("character_id", "first"),
        situation,
        request_id=changes.pop("request_id", "window-cat"),
        **changes,
    )


def test_initiation_reuses_persona_history_and_freezes_external_situation(initiation_system):
    application, system = initiation_system
    historical = send(system, "之前的问题：你吃饭了吗？")
    task_id = request(application)
    with application.database.read() as connection:
        task = application.handler.execution.tasks.get(connection, task_id)
        snapshot = application.handler.execution.tasks.snapshot(connection, task_id)
        assert task["social_turn_id"] and task["initiation_id"]
        turn = application.planner.social.by_id(connection, task["social_turn_id"])
        assert turn.initiation_id == task["initiation_id"]
        assert len(application.planner.social.decisions(connection, turn.social_turn_id)) == 1
        assert turn.chain_id
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert snapshot.perspective.inputs[0].message_id == historical.message_id
        assert snapshot.perspective.trigger_message_ids == (historical.message_id,)
        assert snapshot.current_messages[0].message_id == historical.message_id
        assert snapshot.self.profile and snapshot.self.relationships
        assert "猫把画笔碰倒" in snapshot.perspective.situation
        assert "猫把画笔碰倒" in snapshot.memory.retrieval_query
        original = task["snapshot_json"]
    prepared = application.handler.execution.prepare(task_id, attempt=1)
    assert prepared.invocation.scope.source_kind == "social_turn"
    outputs = OutputRegistry()
    outputs.register(CHARACTER_MESSAGE_CONTRACT, CharacterMessageProposal)
    prompt = project_snapshot(
        snapshot,
        output_contract=CHARACTER_MESSAGE_CONTRACT,
        outputs=outputs,
    )
    assert "眼前的情境" in prompt.messages[0].content
    assert "主动开口" in prompt.messages[0].content
    assert "猫把画笔碰倒" in prompt.messages[0].content
    assert "决定此刻是否想说话" in prompt.messages[0].content
    assert application.handler.execution.prepare(task_id, attempt=1).invocation.context == snapshot
    with application.database.read() as connection:
        assert (
            application.handler.execution.tasks.get(connection, task_id)["snapshot_json"]
            == original
        )


def test_request_idempotency_and_caller_transaction(initiation_system):
    application, _ = initiation_system
    task_id = request(application)
    assert request(application) == task_id
    with pytest.raises(IdempotencyConflict):
        request(application, "另一件事。")
    with (
        pytest.raises(RuntimeError, match="rollback"),
        application.database.transaction() as connection,
    ):
        application.conversation_initiations.request_in(
            connection,
            "community",
            "conversation",
            "first",
            "一件需要谈谈的事。",
            request_id="rolled-back",
        )
        raise RuntimeError("rollback")
    with application.database.read() as connection:
        assert (
            connection.execute("SELECT COUNT(*) FROM conversation_initiations").fetchone()[0] == 1
        )
        assert connection.execute("SELECT COUNT(*) FROM conversation_tasks").fetchone()[0] == 1
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_initiation_management_http_and_community_cleanup(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client, memory_mode="simple")
        application = client.app.state.application
        task_id = request(application)
        response = client.get("/internal/communities/community/tasks")
        assert response.status_code == 200, response.text
        task = response.json()["items"][0]
        assert task["task_id"] == task_id and task["social_turn_id"]
        assert task["initiation_id"]
        response = client.get(
            f"/internal/characters/first/tasks/{task_id}", params={"community_id": "community"}
        )
        assert response.status_code == 200, response.text
        detail = response.json()
        assert detail["initiation"]["initiation_id"] == task["initiation_id"]
        assert detail["initiation"]["request_id"] == "window-cat"
        assert detail["context"]["perspective"]["situation"] == detail["initiation"]["situation"]
        application.communities.update("community", expected_version=1, status="paused")
        response = client.post(
            "/internal/maintenance/cleanup", json={"community_ids": ["community"], "dry_run": False}
        )
        assert response.status_code == 200, response.text
        assert response.json()["deleted"]
        assert response.json()["counts"]["conversation_initiations"] == 1
        with application.database.read() as connection:
            assert not connection.execute("SELECT * FROM conversation_initiations").fetchall()
            assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_game_initiation_uses_turn_source_and_game_send_qualification(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client, memory_mode="simple")
        created, _ = create_game(client)
        game_id = created["game_id"]
        operation(
            client,
            game_id,
            "participants",
            seat_id="white",
            participant={"kind": "character", "character_id": "first"},
        )
        application = client.app.state.application
        conversation_id = created["conversation"]["conversation_id"]
        task_id = application.conversation_initiations.request(
            "community",
            conversation_id,
            "first",
            "等待开局时想打声招呼。",
            request_id="game-opening",
        )
        prepared = application.handler.execution.prepare(task_id, attempt=1)
        assert prepared.invocation.scope.source_kind == "social_turn"
        assert prepared.invocation.context.scope.social_turn_id
        operation(client, game_id, "cancel", reason="player_request")
        with application.database.read() as connection:
            assert (
                application.conversation_expressions.review.context(
                    connection, prepared.invocation.context
                )
                == "source_replaced"
            )
        with pytest.raises(ConflictError):
            application.conversation_initiations.request(
                "community", conversation_id, "first", "另一件事。", request_id="after-cancel"
            )


@pytest.mark.parametrize("change", ["member_left", "archived"])
def test_pending_initiation_cancelled_by_actual_lifecycle(initiation_system, change):
    application, system = initiation_system
    task_id = request(application)
    if change == "member_left":
        application.conversations.leave("community", "conversation", ActorRef("character", "first"))
        application.conversations.join("community", "conversation", ActorRef("character", "first"))
    elif change == "archived":
        application.conversations.archive("community", "conversation")
        with pytest.raises(ConversationArchived):
            request(application, request_id="after-archive")
    else:
        send(system, "我有一个新问题。")
    with application.database.read() as connection:
        row = application.handler.execution.tasks.get(connection, task_id)
        assert row["status"] == "cancelled"
    assert request(application) == task_id
    assert asyncio.run(application.queue.claim("cancelled-test", datetime.now(UTC))) is None


def test_paused_requests_resume_and_only_one_initiation_is_claimed(initiation_system):
    application, _ = initiation_system
    application.communities.update("community", expected_version=1, status="paused")
    first = request(application)
    second = request(application, request_id="another-request", character_id="second")
    assert asyncio.run(application.queue.claim("paused", datetime.now(UTC))) is None
    application.communities.update("community", expected_version=2, status="active")
    application.planner.plan()
    lease = asyncio.run(application.queue.claim("resumed", datetime.now(UTC)))
    assert lease.task_id in (first, second)
    assert asyncio.run(application.queue.claim("another-worker", datetime.now(UTC))) is None
    with application.database.read() as connection:
        assert application.handler.execution.tasks.get(connection, lease.task_id)["initiation_id"]


def test_waiting_request_starts_after_current_turn_ends(initiation_system):
    application, _ = initiation_system
    first = request(application)
    second = request(application, request_id="next", character_id="second")
    with application.database.read() as connection:
        first_task = application.handler.execution.tasks.get(connection, first)
        second_task = application.handler.execution.tasks.get(connection, second)
        assert (
            application.planner.social.by_id(connection, first_task["social_turn_id"]).status
            == "running"
        )
        assert (
            application.planner.social.by_id(connection, second_task["social_turn_id"]).status
            == "pending"
        )
    application.conversations.leave("community", "conversation", ActorRef("character", "first"))
    application.planner.plan()
    lease = asyncio.run(application.queue.claim("next-initiation", datetime.now(UTC)))
    assert lease.task_id == second
    with application.database.read() as connection:
        turn = application.planner.social.by_id(connection, second_task["social_turn_id"])
        assert turn.status == "running" and turn.chain_id
        assert application.planner.social.chain(connection, turn.chain_id).task_count == 2
        assert (
            turn.chain_id
            == application.planner.social.by_id(connection, first_task["social_turn_id"]).chain_id
        )
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.parametrize("kind", ["group", "direct"])
def test_new_player_message_preserves_active_and_waiting_initiations(initiation_system, kind):
    application, _ = initiation_system
    conversation_id = "conversation"
    if kind == "direct":
        conversation_id = "direct"
        application.conversations.create(
            "community",
            "direct",
            (ActorRef("player", "alice"), ActorRef("character", "first")),
            conversation_id=conversation_id,
            player_id="alice",
        )
    tasks = [
        application.conversation_initiations.request(
            "community",
            conversation_id,
            "first",
            "想聊聊刚画好的猫咪。",
            request_id=f"{kind}-{index}",
        )
        for index in range(2)
    ]
    application.intake.send(
        "community", conversation_id, PlayerMessage("alice", "new-player-input", "我有一个新问题。")
    )
    with application.database.read() as connection:
        for task_id in tasks:
            task = application.handler.execution.tasks.get(connection, task_id)
            assert task["status"] == "pending"
            assert application.planner.social.by_id(connection, task["social_turn_id"]).status in (
                "pending",
                "running",
            )
        assert (
            application.handler.execution.tasks.get(connection, tasks[1])["snapshot_json"] is None
        )
    lease = asyncio.run(application.queue.claim("active-initiation", datetime.now(UTC)))
    assert lease.task_id == tasks[0]
    assert asyncio.run(application.queue.claim("same-conversation", datetime.now(UTC))) is None


def test_situation_is_required_material_and_budget_failure_is_durable(initiation_system):
    application, _ = initiation_system
    situation = "完整情景" * 10000
    task_id = request(application, situation)
    with application.database.read() as connection:
        row = application.handler.execution.tasks.get(connection, task_id)
        assert row["status"] == "failed" and row["last_error_code"] == "context_budget_exceeded"
        snapshot = application.handler.execution.tasks.snapshot(connection, task_id)
        assert snapshot.perspective.situation == situation
        assert not connection.execute("SELECT * FROM conversation_results").fetchall()
    assert request(application, situation) == task_id


def test_waiting_request_prepares_latest_context_with_same_round_and_private_situation(
    initiation_system,
):
    application, system = initiation_system
    first = request(application)
    second = request(application, "你想邀请大家散步。", request_id="walk", character_id="second")
    detail = application.conversation_management.task("community", "second", second)
    assert detail["context"] is None
    assert detail["initiation"]["situation"] == "你想邀请大家散步。"
    application.conversations.leave("community", "conversation", ActorRef("character", "first"))
    incoming = send(system, "先告诉我你们想去哪里？")
    application.planner.plan()
    with application.database.read() as connection:
        task = application.handler.execution.tasks.get(connection, second)
        snapshot = application.handler.execution.tasks.snapshot(connection, second)
        assert incoming.message_id in snapshot.perspective.trigger_message_ids
        assert snapshot.perspective.situation == "你想邀请大家散步。"
        assert "猫把画笔碰倒" not in snapshot.model_dump_json()
        turn = application.planner.social.by_id(connection, task["social_turn_id"])
        initial = application.handler.execution.tasks.get(connection, first)
        assert (
            turn.chain_id
            == application.planner.social.by_id(connection, initial["social_turn_id"]).chain_id
        )
        assert connection.execute("SELECT COUNT(*) FROM social_chains").fetchone()[0] == 1
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


def test_opening_progress_is_public_to_original_audience_without_private_situation(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        create_group(client, memory_mode="simple")
        application = client.app.state.application
        before = application.realtime.current("community", "alice")
        request(application, "私有情景417：你想主动问候大家。")
        response = client.get(
            "/api/conversations/conversation/turns", params={"player_id": "alice"}
        )
        assert response.status_code == 200
        turns = response.json()
        assert len(turns) == 1 and turns[0]["status"] == "running"
        assert "私有情景417" not in response.text
        assert turns[0]["input_message_ids"] == []
        outgoing, _, _, _ = application.realtime.scan(before)
        assert any(item["event"] == "conversation.turns_changed" for item in outgoing)
        application.conversations.leave("community", "conversation", ActorRef("player", "bob"))
        application.conversations.join("community", "conversation", ActorRef("player", "bob"))
        request(application, "另一次问候。", request_id="new-opening")
        bob_turns = application.turns.read("community", "conversation", "bob")
        assert len(bob_turns) == 2
        assert all(item.input_message_ids == () for item in bob_turns)


def test_restart_recovers_initiation_lease_with_original_input(initiation_system, tmp_path):
    application, system = initiation_system
    task_id = request(application)
    with application.database.read() as connection:
        original = application.handler.execution.tasks.get(connection, task_id)["snapshot_json"]
    restarted = assemble(
        settings_for(tmp_path, workers=False).model_copy(
            update={"database_path": str(system.database.path)}
        )
    )
    assert request(restarted) == task_id
    lease = asyncio.run(restarted.queue.claim("restarted", datetime.now(UTC)))
    assert lease.task_id == task_id
    with restarted.database.transaction() as connection:
        connection.execute(
            "UPDATE conversation_tasks SET lease_until_utc=? WHERE task_id=?",
            ((datetime.now(UTC) - timedelta(seconds=1)).isoformat(), task_id),
        )
    assert asyncio.run(restarted.queue.recover(datetime.now(UTC))) == 1
    with restarted.database.read() as connection:
        row = restarted.handler.execution.tasks.get(connection, task_id)
        assert row["status"] == "retry_wait" and row["last_error_code"] == "lease_expired"
        assert row["snapshot_json"] == original
        assert restarted.handler.commit.queue.owned(connection, lease, datetime.now(UTC)) is None
        assert connection.execute("SELECT COUNT(*) FROM social_turns").fetchone()[0] == 1
    asyncio.run(restarted.gateway.close())


def test_version_23_upgrade_preserves_old_records_and_snapshots(tmp_path):
    sql = tmp_path / "version23"
    sql.mkdir()
    for source in files("echo_commons.infrastructure.database.sql").iterdir():
        if source.name.endswith(".sql") and int(source.name[:4]) <= 23:
            (sql / source.name).write_text(source.read_text(encoding="utf-8"), encoding="utf-8")
    database = load_history(19, tmp_path / "old.sqlite3")
    assert initialize(database, sql_directory=sql) == 23
    with database.read() as connection:
        names = [
            row[0]
            for row in connection.execute(
                "SELECT name FROM sqlite_master WHERE type='table' AND name NOT LIKE 'sqlite_%' "
                "AND name NOT LIKE 'memory_search_fts_%' AND name!='schema_migrations'"
            )
        ]
        original = {
            name: [dict(row) for row in connection.execute(f'SELECT * FROM "{name}"')]
            for name in names
        }
    assert initialize(database) == initialize(database) == 25
    with database.read() as connection:
        for name, rows in original.items():
            if name in {
                "social_candidates",
                "social_triggers",
                "social_turns",
                "social_chains",
                "participation_decisions",
                "conversation_tasks",
            }:
                continue
            current = [dict(row) for row in connection.execute(f'SELECT * FROM "{name}"')]
            assert current == rows, name
        for task in original["conversation_tasks"]:
            current = dict(
                connection.execute(
                    "SELECT * FROM conversation_tasks WHERE task_id=?", (task["task_id"],)
                ).fetchone()
            )
            assert current["snapshot_id"] == task["snapshot_id"]
            assert current["trace_id"] == task["trace_id"]
            previous_input = json.loads(task["snapshot_json"])
            previous_input["perspective"].pop("root_message_ids", None)
            assert json.loads(current["snapshot_json"]) == previous_input
            if task["status"] in ("pending", "processing", "retry_wait", "suspended"):
                assert current["status"] == "cancelled"
                assert current["last_error_code"] == "scheduling_changed"
                assert current["lease_generation"] == task["lease_generation"] + 1
            else:
                assert current["status"] == task["status"]
        for removed in ("social_candidates", "social_triggers"):
            assert (
                connection.execute(
                    "SELECT 1 FROM sqlite_schema WHERE name=?", (removed,)
                ).fetchone()
                is None
            )
        assert "parent_turn_id" not in {
            row[1] for row in connection.execute("PRAGMA table_info(social_turns)")
        }
        assert "root_turn_id" not in {
            row[1] for row in connection.execute("PRAGMA table_info(social_chains)")
        }
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()


@pytest.mark.model
def test_real_initiation_commit_rollback_reuse_and_export(initiation_system):
    application, _ = initiation_system
    task_id = request(application, "你刚完成一幅猫咪速写，想和在场的人分享这件开心的事。")

    async def generate():
        try:
            lease = await application.queue.claim("real-initiation", datetime.now(UTC))
            assert lease.task_id == task_id
            prepared = application.handler.execution.prepare(
                task_id,
                attempt=lease.attempt,
                deadline_utc=datetime.now(UTC) + timedelta(seconds=80),
            )
            result = await prepared.agent.run(prepared.invocation)
            assert result.status is AgentRunStatus.COMPLETED, result
            return lease, prepared.invocation, result
        finally:
            await application.gateway.close()

    lease, invocation, result = asyncio.run(generate())
    with (
        pytest.raises(RuntimeError, match="rollback"),
        application.database.transaction() as connection,
    ):
        application.conversation_expressions.commit_in(connection, lease, invocation, result)
        raise RuntimeError("rollback")
    with application.database.read() as connection:
        assert not connection.execute("SELECT * FROM messages").fetchall()
        assert not connection.execute("SELECT * FROM conversation_results").fetchall()
    receipt = application.conversation_expressions.commit(lease, invocation, result)
    assert receipt.outcome.disposition is Disposition.COMPLETED
    assert (
        application.conversation_expressions.commit(lease, invocation, result).result_id
        == receipt.result_id
    )
    with application.database.read() as connection:
        message = application.handler.commit.messages.get(
            connection, "conversation", receipt.message_id
        )
        assert message.sender == ActorRef("character", "first")
        assert message.source_turn_id == invocation.context.scope.social_turn_id
        assert message.result_id == receipt.result_id
        assert message.reply_to_message_id is None
        assert connection.execute("SELECT COUNT(*) FROM messages").fetchone()[0] == 1
        assert connection.execute("SELECT COUNT(*) FROM social_turns").fetchone()[0] == 1
        assert not connection.execute("PRAGMA foreign_key_check").fetchall()
    exported = ConversationExport(application.database).export(
        "community", "conversation", first_sequence=1, through_sequence=1, character_id="first"
    )
    assert exported["tasks"][0]["initiation_id"] == invocation.context.scope.initiation_id


@pytest.mark.model
def test_real_initiation_continues_through_social_and_shared_messages(initiation_system):
    application, system = initiation_system
    send(system, "大家今天想画什么？")
    task_id = request(
        application, "你刚画完一幅猫咪速写，想问问在场的人喜欢什么样的猫，请自然地开启这个话题。"
    )

    async def run():
        messages = []
        try:
            for index in range(6):
                lease = await application.queue.claim(
                    f"initiation-chain-{index}", datetime.now(UTC)
                )
                if lease is None:
                    break
                prepared = application.handler.execution.prepare(
                    lease.task_id, attempt=lease.attempt
                )
                snapshot = prepared.invocation.context
                if index == 0:
                    assert lease.task_id == task_id and snapshot.scope.initiation_id
                else:
                    assert snapshot.scope.initiation_id is None
                    assert snapshot.perspective.situation == ""
                    assert messages[-1].message_id in snapshot.perspective.trigger_message_ids
                result = await prepared.agent.run(prepared.invocation)
                receipt = application.conversation_expressions.commit(
                    lease, prepared.invocation, result
                )
                assert receipt.outcome.disposition is Disposition.COMPLETED
                if index == 0:
                    assert receipt.message_id
                if receipt.message_id:
                    with application.database.read() as connection:
                        messages.append(
                            application.handler.commit.messages.get(
                                connection, "conversation", receipt.message_id
                            )
                        )
                application.planner.plan()
            assert await application.queue.claim("chain-finished", datetime.now(UTC)) is None
            assert len(messages) >= 2
            assert messages[0].sender.actor_id == "first"
            assert any(item.sender.actor_id != "first" for item in messages[1:])
            assert all(item.source_turn_id for item in messages)
            with application.database.read() as connection:
                chain = connection.execute("SELECT * FROM social_chains").fetchone()
                assert chain["status"] == "completed"
                assert chain["message_count"] == len(messages) <= chain["max_messages"]
                assert chain["task_count"] <= chain["max_tasks"]
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM messages WHERE sender_kind='player'"
                    ).fetchone()[0]
                    == 1
                )
                assert connection.execute("SELECT COUNT(*) FROM social_chains").fetchone()[0] == 1
                assert not connection.execute("PRAGMA foreign_key_check").fetchall()
        finally:
            await application.gateway.close()

    asyncio.run(run())


@pytest.mark.model
def test_real_silent_initiation_completes_without_followup(initiation_system):
    application, _ = initiation_system
    task_id = request(
        application, "大家正在安静地画画，你也决定继续专心画画。此刻保持沉默，不要对外发言。"
    )

    async def run():
        try:
            lease = await application.queue.claim("silent-initiation", datetime.now(UTC))
            assert lease.task_id == task_id
            assert (await application.handler.execute(lease)).disposition is Disposition.COMPLETED
            application.planner.plan()
            assert await application.queue.claim("no-followup", datetime.now(UTC)) is None
            with application.database.read() as connection:
                assert not connection.execute("SELECT * FROM messages").fetchall()
                chain = connection.execute("SELECT * FROM social_chains").fetchone()
                assert chain["status"] == "completed"
                assert chain["task_count"] == 1 and chain["message_count"] == 0
        finally:
            await application.gateway.close()

    asyncio.run(run())


@pytest.mark.model
def test_real_generated_initiation_rejected_after_member_leaves(initiation_system):
    application, _ = initiation_system
    task_id = request(application)

    async def generate():
        try:
            lease = await application.queue.claim("late-initiation", datetime.now(UTC))
            prepared = application.handler.execution.prepare(task_id, attempt=lease.attempt)
            result = await prepared.agent.run(prepared.invocation)
            assert result.status in (AgentRunStatus.COMPLETED, AgentRunStatus.NO_PROPOSAL)
            return lease, prepared.invocation, result
        finally:
            await application.gateway.close()

    lease, invocation, result = asyncio.run(generate())
    application.conversations.leave("community", "conversation", ActorRef("character", "first"))
    receipt = application.conversation_expressions.commit(lease, invocation, result)
    assert receipt.message_id is None and receipt.outcome.disposition is Disposition.IGNORED
    with application.database.read() as connection:
        assert not connection.execute("SELECT * FROM messages").fetchall()


@pytest.mark.model
def test_real_silent_character_can_consider_new_message_in_same_round(initiation_system):
    application, system = initiation_system
    first_task = request(application, "你决定安静地画画。此刻保持沉默，不要对外发言。")

    async def run():
        first = await application.queue.claim("silent-first", datetime.now(UTC))
        assert first.task_id == first_task
        assert (await application.handler.execute(first)).disposition is Disposition.COMPLETED
        with application.database.read() as connection:
            original = application.handler.execution.tasks.get(connection, first_task)
            turn = application.planner.social.by_id(connection, original["social_turn_id"])
            assert (
                application.planner.social.decisions(connection, turn.social_turn_id)[0].outcome
                == "silent"
            )
        incoming = send(
            system, "小槿，你想画什么植物？", mentions=(ActorRef("character", "first"),)
        )
        application.planner.plan()
        lease = await application.queue.claim("new-visible-content", datetime.now(UTC))
        assert lease and lease.task_id != first_task
        prepared = application.handler.execution.prepare(lease.task_id, attempt=lease.attempt)
        snapshot = prepared.invocation.context
        assert snapshot.scope.character_id == "first" and snapshot.perspective.situation == ""
        assert snapshot.perspective.trigger_message_ids == (incoming.message_id,)
        assert application.planner.plan() == ()
        assert (await application.handler.execute(lease)).disposition is Disposition.COMPLETED
        with application.database.read() as connection:
            assert (
                application.planner.social.by_id(connection, snapshot.scope.social_turn_id).chain_id
                == turn.chain_id
            )
            assert (
                application.planner.social.considered(
                    connection, turn.chain_id, snapshot.scope.membership_id
                )
                == incoming.sequence
            )

    async def execute_and_close():
        try:
            await run()
        finally:
            await application.gateway.close()

    asyncio.run(execute_and_close())


@pytest.mark.model
@pytest.mark.parametrize("quiet_seconds", (0, 6))
def test_real_round_budget_consumes_concurrent_input_and_stops_pending_requests(
    initiation_system, quiet_seconds
):
    application, system = initiation_system
    application.planner.continuation = ContinuationPolicy(max_messages=1, max_tasks=4)
    task_id = request(application, "你刚画完一幅猫咪速写，想向大家分享并问问他们喜欢什么猫。")
    waiting = request(application, "你也想聊聊散步。", request_id="waiting", character_id="second")
    system.intake.quiet_seconds = quiet_seconds

    async def run():
        lease = await application.queue.claim("round-limit", datetime.now(UTC))
        assert lease.task_id == task_id
        prepared = application.handler.execution.prepare(task_id, attempt=lease.attempt)
        generating = asyncio.create_task(prepared.agent.run(prepared.invocation))
        incoming = send(system, "我喜欢橘猫。")
        result = await generating
        assert result.status is AgentRunStatus.COMPLETED
        receipt = application.conversation_expressions.commit(lease, prepared.invocation, result)
        assert receipt.message_id
        assert application.planner.plan() == ()
        with application.database.read() as connection:
            chain = connection.execute("SELECT * FROM social_chains").fetchone()
            assert chain["status"] == "completed" and chain["stop_reason"] == "message_limit"
            assert (
                application.handler.execution.tasks.get(connection, waiting)["status"]
                == "cancelled"
            )
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM social_chain_batches b JOIN input_batch_messages m "
                    "USING(input_batch_id) WHERE b.chain_id=? AND m.message_id=?",
                    (chain["chain_id"], incoming.message_id),
                ).fetchone()[0]
                == 1
            )
            old_batch = connection.execute(
                "SELECT b.input_batch_id,b.status FROM input_batches b "
                "JOIN input_batch_messages m USING(input_batch_id) WHERE m.message_id=?",
                (incoming.message_id,),
            ).fetchone()
            assert old_batch["status"] == "sealed"
        following = send(system, "接下来想聊聊植物。")
        with application.database.read() as connection:
            new_batch = connection.execute(
                "SELECT input_batch_id FROM input_batch_messages WHERE message_id=?",
                (following.message_id,),
            ).fetchone()[0]
            assert new_batch != old_batch["input_batch_id"]
        if quiet_seconds:
            assert application.planner.plan() == ()
            await asyncio.sleep(quiet_seconds + 0.05)
        application.planner.plan()
        with application.database.read() as connection:
            assert connection.execute("SELECT COUNT(*) FROM social_chains").fetchone()[0] == 2
            assert (
                connection.execute(
                    "SELECT COUNT(*) FROM social_chains WHERE status='active'"
                ).fetchone()[0]
                == 1
            )
            assert (
                connection.execute(
                    "SELECT c.status FROM social_chain_batches b "
                    "JOIN social_chains c USING(chain_id) WHERE b.input_batch_id=?",
                    (new_batch,),
                ).fetchone()[0]
                == "active"
            )

    async def execute_and_close():
        try:
            await run()
        finally:
            await application.gateway.close()

    asyncio.run(execute_and_close())
