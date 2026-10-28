import asyncio
import json
from dataclasses import replace
from datetime import UTC, datetime

import pytest
from fastapi.testclient import TestClient
from support.acceptance import create_conversation
from support.application import settings_for
from support.http import create_group
from support.social import build_planning_system, send

from echo_commons.app.lifecycle import application_lifecycle
from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import Disposition
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.modules.social.continuation import ContinuationPolicy
from echo_commons.modules.social.participation import Candidate, RuleBasedParticipationPolicy
from echo_commons.shared.actors import ActorRef


def test_rule_ranks_addressed_then_attempts_then_last_speech():
    policy = RuleBasedParticipationPolicy()
    now = datetime.now(UTC)
    assert (
        policy.select((Candidate("a", False, None), Candidate("b", False, now, replied_to=True)))
        == "b"
    )
    assert (
        policy.select(
            (
                Candidate("a", True, None, chain_attempts=2),
                Candidate("b", True, now, chain_attempts=0),
            )
        )
        == "b"
    )
    assert policy.select((Candidate("a", False, now), Candidate("b", False, None))) == "b"
    assert (
        policy.select((Candidate("a", True, None, "unavailable"), Candidate("b", False, None)))
        == "b"
    )


def test_cancelled_character_leaves_input_for_other_participants(tmp_path):
    system = build_planning_system(tmp_path)
    first = send(system, "大家先看看这条消息")
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    system.planner.plan()
    system.conversations.leave("community", "conversation", ActorRef("character", "second"))
    system.planner.plan()
    with system.database.read() as connection:
        task = connection.execute(
            "SELECT * FROM conversation_tasks WHERE status='pending'"
        ).fetchone()
        assert task["character_id"] == "third"
        snapshot = system.tasks.snapshot(connection, task["task_id"])
        assert snapshot.perspective.trigger_message_ids == (first.message_id,)


def test_duplicate_input_does_not_cancel_current_chain(tmp_path):
    system = build_planning_system(tmp_path)
    source = send(system)
    turn_id = system.planner.plan()[0]
    assert send(system).message_id == source.message_id
    assert system.planner.plan() == ()
    with system.database.read() as connection:
        turn = system.social.by_id(connection, turn_id)
        assert turn.status == "running"
        assert system.social.chain(connection, turn.chain_id).task_count == 1


def test_player_window_blocks_next_arrangement_and_pause_preserves_round(tmp_path):
    system = build_planning_system(tmp_path)
    send(system)
    old_id = system.planner.plan()[0]
    system.intake.quiet_seconds = 6
    send(system, "换一个问题，等我说完")
    assert system.planner.plan() == ()
    system.communities.update("community", expected_version=1, status="paused")
    with system.database.read() as connection:
        old = system.social.by_id(connection, old_id)
        assert old.status == "running"
        assert system.social.chain(connection, old.chain_id).status == "active"
        assert (
            connection.execute("SELECT status FROM conversation_tasks").fetchone()[0] == "suspended"
        )
    system.communities.update("community", expected_version=2, status="active")
    assert system.planner.plan() == ()


def test_task_budget_counts_actual_input_preparation_failures(tmp_path):
    system = build_planning_system(tmp_path)
    system.planner.continuation = ContinuationPolicy(max_messages=3, max_tasks=2)
    context = system.planner.tasks.context
    context.policy = replace(context.policy, input_max_chars=100)
    send(system, "请大家讨论一下晚餐")
    turn_id = system.planner.plan()[0]
    system.planner.plan()
    assert system.planner.plan() == ()
    with system.database.read() as connection:
        turn = system.social.by_id(connection, turn_id)
        chain = system.social.chain(connection, turn.chain_id)
        assert chain.status == "completed" and chain.stop_reason == "task_limit"
        assert chain.task_count == 2 and chain.message_count == 0
        rows = connection.execute("SELECT * FROM conversation_tasks").fetchall()
        assert len(rows) == 2
        assert all(row["status"] == "failed" for row in rows)
        assert all(row["last_error_code"] == "context_budget_exceeded" for row in rows)
        assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_waiting_candidate_cannot_use_rejoined_membership(tmp_path):
    system = build_planning_system(tmp_path)
    send(system)
    turn_id = system.planner.plan()[0]
    system.conversations.leave("community", "conversation", ActorRef("character", "second"))
    system.conversations.join("community", "conversation", ActorRef("character", "second"))
    system.conversations.leave("community", "conversation", ActorRef("character", "first"))
    system.planner.plan()
    system.planner.plan()
    with system.database.read() as connection:
        task = connection.execute(
            "SELECT * FROM conversation_tasks WHERE status='pending'"
        ).fetchone()
        assert task["character_id"] == "third"
        assert system.social.by_id(connection, task["social_turn_id"]).chain_id == (
            system.social.by_id(connection, turn_id).chain_id
        )


def test_public_and_management_views_expose_actual_chain_progress(tmp_path):
    app = create_app(settings_for(tmp_path, workers=False))
    with TestClient(app) as client:
        create_group(client)
        accepted = client.post(
            "/api/conversations/conversation/messages",
            json={
                "player_id": "alice",
                "client_message_id": "first",
                "text": "大家想吃什么？",
                "mentions": [{"kind": "character", "actor_id": "second"}],
            },
        )
        assert accepted.status_code == 202
        application = app.state.application
        turn_id = application.planner.plan()[0]
        turns = client.get(
            "/api/conversations/conversation/turns",
            params={"player_id": "alice"},
        ).json()
        assert turns[0]["chain_id"] and turns[0]["chain_status"] == "active"
        assert turns[0]["participation"][0]["character_id"] == "second"
        detail = application.conversation_management.turn("community", "conversation", turn_id)
        assert detail["chain"]["task_count"] == 1
        assert detail["observations"] == []
        client.post(
            "/api/conversations/conversation/messages",
            json={
                "player_id": "alice",
                "client_message_id": "new",
                "text": "我改主意了。",
            },
        )
        old = client.get(
            "/api/conversations/conversation/turns",
            params={"player_id": "alice"},
        ).json()[0]
        assert old["chain_status"] == "active"
        assert old["chain_stop_reason"] is None
        assert "thought" not in json.dumps(old)
        detail = application.conversation_management.turn("community", "conversation", turn_id)
        assert detail["completion"] is None


@pytest.mark.model
def test_real_round_reads_recent_messages_and_stops_at_budget(tmp_path):
    settings = settings_for(tmp_path, workers=False).model_copy(
        update={
            "debug_capture_enabled": True,
            "debug_capture_path": str(tmp_path / "capture"),
        }
    )

    async def run():
        async with application_lifecycle(settings) as app:
            create_conversation(app)
            submitted = []
            invocations = []
            for index in range(3):
                lease = await app.queue.claim(f"sequential-{index}", utc_now())
                assert lease is not None
                assert await app.queue.claim("same-conversation", utc_now()) is None
                prepared = app.handler.execution.prepare(lease.task_id, attempt=lease.attempt)
                invocations.append(str(prepared.invocation.identity.invocation_id))
                snapshot = prepared.invocation.context
                if index == 0:
                    opening = snapshot.perspective.inputs[0]
                if submitted:
                    previous = submitted[-1]
                    assert previous.message_id in snapshot.perspective.trigger_message_ids
                    assert previous.sender.actor_id != snapshot.scope.character_id
                    assert any(item.text == previous.text for item in snapshot.perspective.inputs)
                result = await prepared.agent.run(prepared.invocation)
                assert result.status.value == "completed", result
                receipt = app.handler.commit.commit(lease, prepared.invocation, result)
                assert receipt.message_id and receipt.outcome.disposition is Disposition.COMPLETED
                duplicate = app.handler.commit.commit(lease, prepared.invocation, result)
                assert duplicate.result_id == receipt.result_id
                with app.database.read() as connection:
                    submitted.append(
                        app.messages.messages.get(connection, "conversation", receipt.message_id)
                    )
                app.planner.plan()
            assert app.planner.plan() == ()
            with app.database.read() as connection:
                chain = connection.execute("SELECT * FROM social_chains").fetchone()
                assert chain["message_count"] == chain["task_count"] == 3
                assert chain["stop_reason"] == "message_limit"
                turns = connection.execute("SELECT * FROM social_turns").fetchall()
                assert len(turns) == 3 and len({turn["chain_id"] for turn in turns}) == 1
                assert all(turn["status"] == "completed" for turn in turns)
                assert (
                    connection.execute("SELECT COUNT(*) FROM social_observations").fetchone()[0]
                    == 2
                )
                assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
            records = [
                json.loads(path.read_text(encoding="utf-8"))
                for path in (tmp_path / "capture").rglob("*.json")
            ]
            calls = [item for item in records if item.get("eventType") == "model_call.started"]
            assert calls
            for index, invocation_id in enumerate(invocations):
                requests = [
                    item["input"]["providerRequest"]["messages"]
                    for item in calls
                    if item["correlation"]["invocationId"] == invocation_id
                ]
                assert requests
                contents = "\n".join(message.get("content") or "" for message in requests[0])
                assert opening.message_id not in contents
                assert "本次触发消息：" not in contents and "原始玩家输入" not in contents
                if index:
                    assert submitted[index - 1].text in contents
                    assert submitted[index - 1].message_id not in contents
            print("实际群聊发言：", [(item.sender.actor_id, item.text) for item in submitted])

    asyncio.run(run())


@pytest.mark.model
def test_real_group_silence_tries_every_candidate_without_empty_messages(tmp_path):
    settings = settings_for(tmp_path, workers=False)

    async def run():
        async with application_lifecycle(settings) as app:
            create_conversation(
                app, greeting="我需要安静一下，两位都不用回复。请保持沉默，不要生成对外发言。"
            )
            for index in range(2):
                lease = await app.queue.claim(f"quiet-{index}", utc_now())
                assert lease
                outcome = await app.handler.execute(lease)
                assert outcome.disposition is Disposition.COMPLETED
                app.planner.plan()
            assert await app.queue.claim("exhausted", utc_now()) is None
            with app.database.read() as connection:
                active = connection.execute(
                    "SELECT * FROM social_chains ORDER BY created_at_utc DESC"
                ).fetchone()
                assert active["status"] == "completed"
                assert active["task_count"] == 2 and active["message_count"] == 0
                assert active["stop_reason"] == "quiet"
                assert (
                    connection.execute(
                        "SELECT COUNT(*) FROM messages WHERE sender_kind='character'"
                    ).fetchone()[0]
                    == 0
                )
                decisions = connection.execute(
                    "SELECT p.outcome FROM participation_decisions p JOIN social_turns s "
                    "USING(social_turn_id) WHERE s.chain_id=?",
                    (active["chain_id"],),
                ).fetchall()
                assert [item[0] for item in decisions] == ["silent", "silent"]

    asyncio.run(run())


@pytest.mark.model
def test_real_inflight_reply_survives_new_input_and_preserves_unseen_progress(tmp_path):
    settings = settings_for(tmp_path, workers=False)

    async def run():
        async with application_lifecycle(settings) as app:
            create_conversation(app)
            lease = await app.queue.claim("inflight", utc_now())
            prepared = app.handler.execution.prepare(lease.task_id, attempt=lease.attempt)
            old_upper = prepared.invocation.context.scope.observation_upper_sequence
            generating = asyncio.create_task(prepared.agent.run(prepared.invocation))
            incoming = app.intake.send(
                "community",
                "conversation",
                PlayerMessage("player", "change", "换个话题，请说说你喜欢的植物。"),
            )
            result = await generating
            receipt = app.handler.commit.commit(lease, prepared.invocation, result)
            assert receipt.outcome.disposition is Disposition.COMPLETED
            assert receipt.message_id
            with app.database.read() as connection:
                task = app.handler.execution.tasks.get(connection, lease.task_id)
                turn = app.planner.social.by_id(connection, task["social_turn_id"])
                assert (
                    app.planner.social.considered(connection, turn.chain_id, task["membership_id"])
                    == old_upper
                    < incoming.sequence
                )
            app.planner.plan()
            next_lease = await app.queue.claim("new-input", utc_now())
            assert next_lease and next_lease.task_id != lease.task_id
            following = app.handler.execution.prepare(
                next_lease.task_id, attempt=next_lease.attempt
            )
            assert (
                incoming.message_id in following.invocation.context.perspective.trigger_message_ids
            )
            with app.database.read() as connection:
                next_turn = app.planner.social.by_id(
                    connection, following.invocation.context.scope.social_turn_id
                )
                assert next_turn.chain_id == turn.chain_id
                assert connection.execute("SELECT COUNT(*) FROM social_chains").fetchone()[0] == 1

    asyncio.run(run())
