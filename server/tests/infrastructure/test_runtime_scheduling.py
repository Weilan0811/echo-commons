import asyncio
import time
from dataclasses import replace
from uuid import uuid4

from fastapi.testclient import TestClient
from support.activities import activity_game, prepare
from support.application import settings_for
from test_activity_scheduling import (
    claim,
    expire_legacy,
    pending_games,
    settings_with_history,
)

from echo_commons.app.main import create_app
from echo_commons.execution.clock import utc_now
from echo_commons.execution.contracts import SchedulingLane, TaskCandidate, TaskOccupancy
from echo_commons.execution.model_budget import ModelBudget
from echo_commons.execution.scheduling import SchedulingQueue
from echo_commons.modules.conversations.domain.message import PlayerMessage
from echo_commons.shared.actors import ActorRef


def test_global_queue_claims_game_chat_and_reflection_in_weighted_order(tmp_path):
    with TestClient(create_app(settings_with_history(tmp_path))) as client:
        expire_legacy(client)
        app = client.app.state.application
        pending_games(client, 3)
        app.conversations.create(
            "community",
            "direct",
            (ActorRef("player", "alice"), ActorRef("character", "first")),
            conversation_id="nearby",
        )
        message = app.intake.send(
            "community",
            "nearby",
            PlayerMessage("alice", uuid4().hex, "周末一起做饭吧。"),
        )
        task_id = app.conversation_initiations.request(
            "community",
            "nearby",
            "first",
            "回应周末安排。",
            request_id="nearby-reply",
        )
        segment = app.memory_sealing.seal("community", "first")
        app.reflection.start_segment("community", "first", segment.segment_id)
        leases = [claim(client, f"worker-{index}") for index in range(5)]
        assert [lease.task_kind for lease in leases] == [
            "activity_turn",
            "activity_expression",
            "activity_turn",
            "conversation_reply",
            "reflection",
        ]
        assert leases[3].task_id == task_id
        assert leases[4].scheduling_lane == SchedulingLane.BACKGROUND
        assert len({lease.task_id for lease in leases}) == 5
        assert not app.gateway._clients
        assert message.message_id


def test_dependency_summary_inherits_waiting_conversations_lane(tmp_path):
    from test_memory_context_budget import pressure_application

    app, task_id = pressure_application(tmp_path, ask=True)

    async def run():
        await app.supervisor.workers["conversation-memory"].run_once()
        queue = app.supervisor.workers["tasks-0"].queue
        with app.database.read() as connection:
            waiting = queue.waiting_scopes_in(connection)
            candidates = app.reflection_queue.candidates_in(connection, utc_now())
        assert waiting[("community", "first")] == SchedulingLane.EXCHANGE
        assert candidates and all(c.lane == SchedulingLane.EXCHANGE for c in candidates)
        lease = await queue.claim("summary-worker", utc_now())
        assert lease.task_kind == "reflection" and lease.scheduling_lane == SchedulingLane.EXCHANGE
        assert lease.task_id != task_id
        assert not app.gateway._clients
        await app.gateway.close()

    asyncio.run(run())


def test_shared_model_capacity_is_weighted_fifo_and_cancel_releases_waiters(tmp_path):
    with TestClient(create_app(settings_with_history(tmp_path))) as client:
        budget = ModelBudget(client.app.state.application.gateway, 1)

        async def run():
            entered = []

            async def acquire(lane, index):
                async with budget.reservation(lane), budget.slot():
                    assert budget._active == 1
                    entered.append((lane, index))

            async with budget.slot(SchedulingLane.BACKGROUND):
                tasks = [
                    asyncio.create_task(acquire(lane, index))
                    for lane in SchedulingLane
                    for index in range(4)
                ]
                await asyncio.sleep(0)
                tasks[-1].cancel()
                await asyncio.gather(tasks[-1], return_exceptions=True)
            await asyncio.gather(*tasks[:-1])
            assert [lane for lane, _ in entered[:10]] == [
                SchedulingLane.TURN,
                SchedulingLane.EXCHANGE,
                SchedulingLane.TURN,
                SchedulingLane.EXCHANGE,
                SchedulingLane.BACKGROUND,
            ] * 2
            for lane in SchedulingLane:
                assert [i for actual, i in entered if actual == lane] == list(
                    range(3 if lane == SchedulingLane.BACKGROUND else 4)
                )
            assert budget._active == 0 and not budget._waiting

        client.portal.call(run)


def test_scope_rules_serialize_decisions_and_order_speech_without_blocking_other_windows():
    scope = ("public_expression", "game-chat", "first")
    speech = TaskCandidate("new", "activity_expression", "2", "2", (scope,))
    waiting = TaskOccupancy(
        "old", "activity_expression", (scope,), ("1", "activity_expression", "old")
    )
    assert not SchedulingQueue.allowed(speech, (waiting,))
    other = replace(speech, required_scopes=(("public_expression", "group-chat", "first"),))
    assert SchedulingQueue.allowed(other, (waiting,))
    earlier = replace(speech, task_id="earlier", created_at_utc="0")
    assert SchedulingQueue.allowed(earlier, (waiting,))
    assert not SchedulingQueue.allowed(earlier, (replace(waiting, waiting_since=None),))
    decision = TaskOccupancy("thinking", "activity_reply", (("activity_decision", "participant"),))
    action = TaskCandidate(
        "turn", "activity_turn", "2", "2", (("activity_decision", "participant"),)
    )
    assert not SchedulingQueue.allowed(action, (decision,))
    assert SchedulingQueue.allowed(speech, (decision,))


def test_activity_invocation_uses_renewed_lease_after_resource_wait(tmp_path):
    with TestClient(create_app(settings_for(tmp_path, workers=False))) as client:
        game = activity_game(client)
        app = client.app.state.application
        (task_id,) = app.activity_coordinator.scan()
        with app.database.read() as connection:
            row = dict(app.activity_queue.repository.get(connection, task_id))
        snapshot = prepare(client, game, kind="turn", input_id=row["input_id"])
        app.activity_queue.policy = replace(app.activity_queue.policy, lease_seconds=0.5)
        lease = client.portal.call(app.activity_queue.claim, "waiting-model", utc_now())
        original = app.activity_execution._load(lease)
        time.sleep(0.3)
        assert client.portal.call(app.activity_queue.renew, lease, utc_now())
        time.sleep(0.25)
        assert lease.expires_at_utc < utc_now()
        invocation, _ = app.activity_execution.invocation(lease, original, snapshot)
        assert invocation.execution_policy.deadline_utc > utc_now()
        assert not app.gateway._clients
